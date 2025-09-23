// WAN workflow с упорядоченными нодами для правильной валидации зависимостей
export default (
  {
    prompt = 'photo-realistic, natural lighting, sharp details, 35mm film look, subtle skin texture',
    negative_prompt = '',
  },
  options = {
    width: 1920,
    height: 1088,
    seed: Math.floor(Math.random() * 100000000000000),
    steps: 18,
    cfg: 2,
    sampler: 'res_2s',
    scheduler: 'bong_tangent',
    image_influence: 0.5,
    useInputImage: true,
    inputImageFiles: null,
  }
) => {
  const {
    width,
    height,
    seed,
    steps,
    cfg,
    sampler,
    scheduler,
    image_influence,
    useInputImage,
    inputImageFiles,
  } = options;
  const aLen = 2;
  const aStart = steps / 2 + ((image_influence * 2 - 1) * (steps - aLen)) / 2;
  console.log('🔧 Генерируем упорядоченный WAN i2i workflow:', {
    prompt: typeof prompt === 'string' ? prompt.substring(0, 80) : '',
    width,
    height,
    seed,
    aStart,
    aLen,
    image_influence,
  });

  const workflow = {};

  // Base loaders
  workflow[8] = {
    inputs: { vae_name: 'Wan2.1_VAE.pth' },
    class_type: 'VAELoader',
  };
  workflow[22] = {
    inputs: {
      clip_name: 'umt5_xxl_fp8_e4m3fn_scaled.safetensors',
      type: 'wan',
      device: 'default',
    },
    class_type: 'CLIPLoader',
  };
  workflow[46] = {
    inputs: {
      unet_name: 'wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors',
      weight_dtype: 'fp8_e4m3fn_fast',
    },
    class_type: 'UNETLoader',
  };
  workflow[47] = {
    inputs: {
      unet_name: 'wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors',
      weight_dtype: 'fp8_e4m3fn_fast',
    },
    class_type: 'UNETLoader',
  };

  // Loras
  workflow[43] = {
    inputs: {
      lora_name: 'Wan2.1_T2V_14B_FusionX_LoRA.safetensors',
      strength_model: 0.8,
      model: [47, 0],
    },
    class_type: 'LoraLoaderModelOnly',
  };
  workflow[44] = {
    inputs: {
      lora_name:
        'lightx2v_T2V_14B_cfg_step_distill_v2_lora_rank128_bf16.safetensors',
      strength_model: 0.4,
      model: [43, 0],
    },
    class_type: 'LoraLoaderModelOnly',
  };
  workflow[45] = {
    inputs: {
      lora_name:
        'WAN2.1_SmartphoneSnapshotPhotoReality_v1_by-AI_Characters.safetensors',
      strength_model: 1.0,
      model: [44, 0],
    },
    class_type: 'LoraLoaderModelOnly',
  };
  workflow[90] = {
    inputs: {
      lora_name: 'Wan2.1_T2V_14B_FusionX_LoRA.safetensors',
      strength_model: 1.25,
      model: [46, 0],
    },
    class_type: 'LoraLoaderModelOnly',
  };
  workflow[91] = {
    inputs: {
      lora_name:
        'lightx2v_T2V_14B_cfg_step_distill_v2_lora_rank128_bf16.safetensors',
      strength_model: 0.4,
      model: [90, 0],
    },
    class_type: 'LoraLoaderModelOnly',
  };

  // Model sampling
  workflow[59] = {
    inputs: { shift: 8.0, model: [91, 0] },
    class_type: 'ModelSamplingSD3',
  };
  workflow[60] = {
    inputs: { shift: 8.0, model: [45, 0] },
    class_type: 'ModelSamplingSD3',
  };

  // Text encoders
  workflow[3] = {
    inputs: { text: prompt, clip: [22, 0] },
    class_type: 'CLIPTextEncode',
  };
  workflow[81] = {
    inputs: { text: negative_prompt || '', clip: [22, 0] },
    class_type: 'CLIPTextEncode',
  };

  // Image input(s). Поддержка до двух изображений: 1-е — контент, 2-е — стиль
  /** @type {string[]} */
  let imageFiles = ['img1.png'];
  /** @type {string[]} */
  const filesCandidate = Array.isArray(inputImageFiles) ? inputImageFiles : [];
  if (useInputImage && filesCandidate.length > 0) {
    imageFiles = filesCandidate;
  }
  const contentFile = imageFiles[0];
  const styleFile = imageFiles[1];

  // Контент: загрузка -> ресайз -> VAEEncode
  workflow[94] = {
    inputs: { image: contentFile },
    class_type: 'LoadImage',
  };
  workflow[95] = {
    inputs: {
      width: width,
      height: height,
      upscale_method: 'nearest-exact',
      keep_proportion: 'crop',
      pad_color: '0, 0, 0',
      crop_position: 'center',
      divisible_by: 64,
      device: 'cpu',
      image: [94, 0],
    },
    class_type: 'ImageResizeKJv2',
  };
  workflow[96] = {
    inputs: { pixels: [95, 0], vae: [8, 0] },
    class_type: 'VAEEncode',
  };

  // Если пришло второе изображение (стиль) — добавляем ветку и ReferenceLatent
  let positiveConditionNode = [3, 0];
  if (styleFile) {
    workflow[97] = {
      inputs: { image: styleFile },
      class_type: 'LoadImage',
    };
    workflow[98] = {
      inputs: {
        width: width,
        height: height,
        upscale_method: 'nearest-exact',
        keep_proportion: 'crop',
        pad_color: '0, 0, 0',
        crop_position: 'center',
        divisible_by: 64,
        device: 'cpu',
        image: [97, 0],
      },
      class_type: 'ImageResizeKJv2',
    };
    workflow[99] = {
      inputs: { pixels: [98, 0], vae: [8, 0] },
      class_type: 'VAEEncode',
    };
    workflow[100] = {
      inputs: { conditioning: [3, 0], latent: [99, 0] },
      class_type: 'ReferenceLatent',
    };
    positiveConditionNode = [100, 0];
  }

  // Samplers
  workflow[35] = {
    inputs: {
      add_noise: 'enable',
      noise_seed: seed,
      steps,
      cfg,
      sampler_name: sampler || 'res_2s',
      scheduler: scheduler || 'bong_tangent',
      start_at_step: aStart,
      end_at_step: aStart + aLen,
      return_with_leftover_noise: 'enable',
      model: [59, 0],
      positive: positiveConditionNode,
      negative: [81, 0],
      latent_image: [96, 0],
    },
    class_type: 'KSamplerAdvanced',
  };
  workflow[36] = {
    inputs: {
      add_noise: 'disable',
      noise_seed: seed,
      steps,
      cfg,
      sampler_name: sampler || 'res_2s',
      scheduler: scheduler || 'bong_tangent',
      start_at_step: aStart + aLen,
      end_at_step: 999,
      return_with_leftover_noise: 'disable',
      model: [60, 0],
      positive: positiveConditionNode,
      negative: [81, 0],
      latent_image: [35, 0],
    },
    class_type: 'KSamplerAdvanced',
  };

  // Decode + Save (clean output)
  workflow[9] = {
    inputs: { samples: [36, 0], vae: [8, 0] },
    class_type: 'VAEDecode',
  };
  workflow[62] = {
    inputs: { grain_intensity: 0.01, saturation_mix: 0.2, images: [9, 0] },
    class_type: 'FastFilmGrain',
  };
  workflow[10] = {
    inputs: { filename_prefix: 'ComfyUI', images: [62, 0] },
    class_type: 'SaveImage',
  };

  // Normalize numeric link ids to strings for ComfyUI
  Object.values(workflow).forEach((node) => {
    if (!node.inputs) return;
    Object.keys(node.inputs).forEach((key) => {
      const val = node.inputs[key];
      if (Array.isArray(val) && typeof val[0] === 'number') {
        node.inputs[key][0] = String(val[0]);
      }
    });
  });

  return workflow;
};
