export default (prompt, options = {}) => {
  const {
    steps = 20,
    width = 1024,
    height = 1024,
    seed = Math.floor(Math.random() * 1000000000000000),
    cfg = 1,
    sampler_name = 'euler',
    scheduler = 'simple',
    useInputImage = true, // Новый параметр для контроля использования входного изображения
    useLora = false, // Включение поддержки LoRA
    loras = [], // Массив LoRA для загрузки
    guidance = 2.5,
    denoise = 1,
  } = options;

  // Базовые узлы, которые нужны всегда
  const workflow = {
    6: {
      inputs: {
        text: `${prompt}`,
        clip:
          useLora && loras.length > 0
            ? [`${400 + loras.length - 1}`, 1]
            : ['38', 0],
      },
      class_type: 'CLIPTextEncode',
      _meta: {
        title: 'CLIP Text Encode (Positive Prompt)',
      },
    },
    8: {
      inputs: {
        samples: ['31', 0],
        vae: ['39', 0],
      },
      class_type: 'VAEDecode',
      _meta: {
        title: 'VAE Decode',
      },
    },
    31: {
      inputs: {
        seed: seed,
        steps: steps,
        cfg: cfg,
        sampler_name: sampler_name,
        scheduler: scheduler,
        denoise: denoise,
        model:
          useLora && loras.length > 0
            ? [`${400 + loras.length - 1}`, 0]
            : ['37', 0],
        positive: ['35', 0],
        negative: ['135', 0],
        latent_image: useInputImage ? ['124', 0] : ['300', 0], // Условный выбор источника latent
      },
      class_type: 'KSampler',
      _meta: {
        title: 'KSampler',
      },
    },
    35: {
      inputs: {
        guidance: guidance,
        conditioning: useInputImage ? ['177', 0] : ['6', 0], // Условный выбор conditioning
      },
      class_type: 'FluxGuidance',
      _meta: {
        title: 'FluxGuidance',
      },
    },
    37: {
      inputs: {
        unet_name: 'flux1-dev-kontext_fp8_scaled.safetensors',
        weight_dtype: 'default',
      },
      class_type: 'UNETLoader',
      _meta: {
        title: 'Load Diffusion Model',
      },
    },
    38: {
      inputs: {
        clip_name1: 'clip_l.safetensors',
        clip_name2: 't5xxl_fp8_e4m3fn_scaled.safetensors',
        type: 'flux',
        device: 'default',
      },
      class_type: 'DualCLIPLoader',
      _meta: {
        title: 'DualCLIPLoader',
      },
    },
    39: {
      inputs: {
        vae_name: 'ae.safetensors',
      },
      class_type: 'VAELoader',
      _meta: {
        title: 'Load VAE',
      },
    },
    135: {
      inputs: {
        conditioning: ['6', 0],
      },
      class_type: 'ConditioningZeroOut',
      _meta: {
        title: 'ConditioningZeroOut',
      },
    },
    136: {
      inputs: {
        filename_prefix: 'ComfyUI',
        images: ['8', 0],
      },
      class_type: 'SaveImage',
      _meta: {
        title: 'Save Image',
      },
    },
  };

  // Создание цепочки LoRA, если включена поддержка
  if (useLora && loras.length > 0) {
    console.log('🔧 Добавляем LoRA цепочку:', loras.length, 'моделей');

    // Предупреждение о возможной несовместимости WAN-адаптеров с Flux
    const looksLikeWan = loras.some((l) =>
      /wan|t2v|lightx2v/i.test(l.name || '')
    );
    if (looksLikeWan) {
      console.warn(
        '⚠️ Обнаружены LoRA, похожие на WAN (wan/t2v/lightx2v). Для модели Flux они, скорее всего, не применяются. Используйте LoRA, совместимые с Flux.'
      );
    }

    // Создаем каскад LoRA загрузчиков, начиная с ID 400. Каскадируем и model, и clip
    loras.forEach((lora, index) => {
      const nodeId = 400 + index;
      const previousModel = index === 0 ? ['37', 0] : [`${400 + index - 1}`, 0];
      const previousClip = index === 0 ? ['38', 0] : [`${400 + index - 1}`, 1];

      workflow[nodeId] = {
        inputs: {
          lora_name: lora.name,
          strength_model: lora.strength || 1.0,
          strength_clip: lora.strength_clip || 1.0,
          model: previousModel,
          clip: previousClip,
        },
        class_type: 'LoraLoader',
        _meta: {
          title: `LoRA ${index + 1}: ${lora.name}`,
        },
      };

      console.log(
        `✅ LoRA ${index + 1} добавлена:`,
        lora.name,
        'сила:',
        lora.strength || 1.0,
        'clip:',
        lora.strength_clip || 1.0
      );
    });
  }

  // Добавляем узлы для работы с входным изображением, если это необходимо
  if (useInputImage) {
    // Узлы для загрузки и обработки изображений
    workflow[142] = {
      inputs: {
        image: 'img1.png',
      },
      class_type: 'LoadImage',
      _meta: {
        title: 'Load Image',
      },
    };

    workflow[146] = {
      inputs: {
        direction: 'right',
        match_image_size: true,
        spacing_width: 0,
        spacing_color: 'white',
        image1: ['142', 0],
        image2: ['142', 0],
      },
      class_type: 'ImageStitch',
      _meta: {
        title: 'Image Stitch',
      },
    };

    workflow[42] = {
      inputs: {
        image: ['146', 0],
      },
      class_type: 'FluxKontextImageScale',
      _meta: {
        title: 'FluxKontextImageScale',
      },
    };

    workflow[200] = {
      inputs: {
        upscale_method: 'lanczos',
        width: width,
        height: height,
        crop: 'center',
        image: ['42', 0],
      },
      class_type: 'ImageScale',
      _meta: {
        title: 'Image Scale',
      },
    };

    workflow[124] = {
      inputs: {
        pixels: ['200', 0],
        vae: ['39', 0],
      },
      class_type: 'VAEEncode',
      _meta: {
        title: 'VAE Encode',
      },
    };

    workflow[173] = {
      inputs: {
        images: ['200', 0],
      },
      class_type: 'PreviewImage',
      _meta: {
        title: 'Preview Image',
      },
    };

    workflow[177] = {
      inputs: {
        conditioning: ['6', 0],
        latent: ['124', 0],
      },
      class_type: 'ReferenceLatent',
      _meta: {
        title: 'ReferenceLatent',
      },
    };
  } else {
    // Узел для создания пустого latent пространства для text-to-image генерации
    workflow[300] = {
      inputs: {
        width: width,
        height: height,
        batch_size: 1,
      },
      class_type: 'EmptyLatentImage',
      _meta: {
        title: 'Empty Latent Image',
      },
    };
  }

  return workflow;
};

// Пресеты LoRA удалены: используйте совместимые с Flux LoRA и передавайте их в options.loras
