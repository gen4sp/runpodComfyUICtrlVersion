// WAN workflow с упорядоченными нодами для правильной валидации зависимостей
export default (
  { prompt, negative_prompt },
  options = {
    width: 1920,
    height: 1088,
    seed: Math.floor(Math.random() * 100000000000000),
    steps: 4,
    cfg: 1,
    sampler: 'res_2s',
    scheduler: 'bong_tangent',
  }
) => {
  const { width, height, seed, steps, cfg, sampler, scheduler } = options;

  console.log('🔧 Генерируем упорядоченный WAN workflow:', {
    prompt: typeof prompt === 'string' ? prompt.substring(0, 50) : '',
    width,
    height,
    seed,
  });

  // Создаем workflow в строгом порядке зависимостей
  const workflow = {};

  // 1. STEP: Базовые loaders (самые независимые компоненты)

  // VAELoader (id: 8)
  workflow[8] = {
    inputs: {
      vae_name: 'Wan2.1_VAE.pth',
    },
    class_type: 'VAELoader',
  };

  // CLIPLoader (id: 22)
  workflow[22] = {
    inputs: {
      clip_name: 'umt5_xxl_fp8_e4m3fn_scaled.safetensors',
      type: 'wan',
      device: 'default',
    },
    class_type: 'CLIPLoader',
  };

  // UNETLoader - high noise (id: 46)
  workflow[46] = {
    inputs: {
      unet_name: 'wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors',
      weight_dtype: 'fp8_e4m3fn_fast',
    },
    class_type: 'UNETLoader',
  };

  // UNETLoader - low noise (id: 47)
  workflow[47] = {
    inputs: {
      unet_name: 'wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors',
      weight_dtype: 'fp8_e4m3fn_fast',
    },
    class_type: 'UNETLoader',
  };

  // 2. STEP: Lora loaders (зависят от базовых моделей)

  // LoraLoaderModelOnly (id: 43) - зависит от 47
  workflow[43] = {
    inputs: {
      lora_name: 'Wan2.1_T2V_14B_FusionX_LoRA.safetensors',
      strength_model: 0.8000000000000002,
      model: [47, 0],
    },
    class_type: 'LoraLoaderModelOnly',
  };

  // LoraLoaderModelOnly (id: 44) - зависит от 43
  workflow[44] = {
    inputs: {
      lora_name:
        'lightx2v_T2V_14B_cfg_step_distill_v2_lora_rank128_bf16.safetensors',
      strength_model: 0.4000000000000001,
      model: [43, 0],
    },
    class_type: 'LoraLoaderModelOnly',
  };

  // LoraLoaderModelOnly (id: 45) - зависит от 44
  workflow[45] = {
    inputs: {
      lora_name:
        'WAN2.1_SmartphoneSnapshotPhotoReality_v1_by-AI_Characters.safetensors',
      strength_model: 1.2000000000000002,
      model: [44, 0],
    },
    class_type: 'LoraLoaderModelOnly',
  };

  // LoraLoaderModelOnly (id: 90) - зависит от 46
  workflow[90] = {
    inputs: {
      lora_name: 'Wan2.1_T2V_14B_FusionX_LoRA.safetensors',
      strength_model: 1.0000000000000002,
      model: [46, 0],
    },
    class_type: 'LoraLoaderModelOnly',
  };

  // LoraLoaderModelOnly (id: 91) - зависит от 90
  workflow[91] = {
    inputs: {
      lora_name:
        'lightx2v_T2V_14B_cfg_step_distill_v2_lora_rank128_bf16.safetensors',
      strength_model: 0.4000000000000001,
      model: [90, 0],
    },
    class_type: 'LoraLoaderModelOnly',
  };

  // 3. STEP: ModelSampling настройки

  // ModelSamplingSD3 (id: 59) - зависит от 91
  workflow[59] = {
    inputs: {
      shift: 8.000000000000002,
      model: [91, 0],
    },
    class_type: 'ModelSamplingSD3',
  };

  // ModelSamplingSD3 (id: 60) - зависит от 45
  workflow[60] = {
    inputs: {
      shift: 8.000000000000002,
      model: [45, 0],
    },
    class_type: 'ModelSamplingSD3',
  };

  // 4. STEP: Text encoding (зависит от CLIP)

  // CLIPTextEncode - positive (id: 3)
  workflow[3] = {
    inputs: {
      text:
        prompt ||
        'photo-realistic subject, natural lighting, sharp details, 35mm film look',
      clip: [22, 0],
    },
    class_type: 'CLIPTextEncode',
  };

  // CLIPTextEncode - negative (id: 81)
  workflow[81] = {
    inputs: {
      text: negative_prompt || '',
      clip: [22, 0],
    },
    class_type: 'CLIPTextEncode',
  };

  // 5. STEP: Latent generation

  // EmptyHunyuanLatentVideo (id: 5)
  workflow[5] = {
    inputs: {
      width: width,
      height: height,
      batch_size: 1,
      length: 1,
    },
    class_type: 'EmptyHunyuanLatentVideo',
  };

  // 6. STEP: Sampling (зависит от моделей, текста и latent)

  // KSamplerAdvanced - first pass (id: 35)
  workflow[35] = {
    inputs: {
      add_noise: 'enable',
      noise_seed: seed,
      control_after_generate: 'increment',
      steps,
      cfg,
      sampler_name: sampler || 'res_2s',
      scheduler: scheduler || 'bong_tangent',
      start_at_step: 0,
      end_at_step: 2,
      return_with_leftover_noise: 'enable',
      model: [59, 0],
      positive: [3, 0],
      negative: [81, 0],
      latent_image: [5, 0],
    },
    class_type: 'KSamplerAdvanced',
  };

  // KSamplerAdvanced - second pass (id: 36)
  workflow[36] = {
    inputs: {
      add_noise: 'disable',
      noise_seed: seed,
      control_after_generate: 'increment',
      steps,
      cfg,
      sampler_name: sampler || 'res_2s',
      scheduler: scheduler || 'bong_tangent',
      start_at_step: 2,
      end_at_step: 999,
      return_with_leftover_noise: 'disable',
      model: [60, 0],
      positive: [3, 0],
      negative: [81, 0],
      latent_image: [35, 0],
    },
    class_type: 'KSamplerAdvanced',
  };

  // 7. STEP: Decode и Save (финальные операции)

  // VAEDecode (id: 9) - КРИТИЧЕСКАЯ НОДА
  workflow[9] = {
    inputs: {
      samples: [36, 0],
      vae: [8, 0],
    },
    class_type: 'VAEDecode',
  };

  // SaveImage (id: 10) - финальная нода
  workflow[10] = {
    inputs: {
      images: [9, 0],
      filename_prefix: 'ComfyUI',
    },
    class_type: 'SaveImage',
  };

  console.log(
    '✅ Упорядоченный workflow создан, всего нод:',
    Object.keys(workflow).length
  );
  console.log('🔍 Порядок нод:', Object.keys(workflow).join(' -> '));
  console.log('✨ Нода 9 определена:', !!workflow[9]);

  // Преобразуем все ссылки вида [9, 0] в строки ['9', 0] для корректной
  // валидации на Python стороне ComfyUI (dict ключи строковые)
  Object.values(workflow).forEach((node) => {
    if (!node.inputs) return;
    Object.keys(node.inputs).forEach((key) => {
      const val = node.inputs[key];
      if (Array.isArray(val) && typeof val[0] === 'number') {
        // Заменяем числовой ID на строку
        node.inputs[key][0] = String(val[0]);
      }
    });
  });

  return workflow;
};
