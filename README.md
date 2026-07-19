# ZF-ComfyUI-PromptDirector

[简体中文](README.zh-CN.md)

An early public-testing release of a purpose-driven prompt director for ComfyUI. It turns a user prompt, a theme/worldview, a professional use case, and a visual method into one independent Chinese image-generation task per requested image.

## Material-Source Attribution / 素材来源说明

The material catalogs used, organized, and expanded by the current and future versions of this plugin—including use cases, creative directions, case-inspired ideas, and related prompt-material references—originate from the material collections and sharing of **远古大呲花**. This attribution is included with the author's consent.

- Source author / 来源作者: **远古大呲花**
- Bilibili profile / B站主页: <https://space.bilibili.com/59550296>
- Engineering scope / 工程范围: This repository provides the plugin code and its engineering work, including structured cataloging, purpose/visual-method mapping, prompt-workflow integration, and ComfyUI node implementation. The original material source and the author's contribution remain attributed to 远古大呲花.
- Update note / 更新说明: Future additions or revisions to the material catalogs will continue to record this source. If the source arrangement changes, this section will be updated accordingly.
- Clarification / 贡献边界: This attribution identifies the material source. Unless separately agreed in writing, it does not mean that 远古大呲花 authored the plugin code or guarantees the plugin's functions, model behavior, or downstream generated content.

Feedback from different local language models, vision-language models, image models, and workflow layouts is welcome. Please open a GitHub Issue with reproducible settings and expected behavior. Do not include private images, model files, tokens, or API keys.

## Highlights

- Purpose-driven prompt planning with 31 use cases and 38 visual methods.
- Multi-image task counts are created by plugin code instead of relying on a language model to count correctly.
- User-core, theme-creation, and storyboard modes.
- Three output-detail levels for lightweight, mainstream, and strong image models.
- Dynamic reference-image creativity: extract reusable concepts, element pools, composition, materials, and lighting without feeding the source latent into the sampler.
- A temporary reference-image purpose/creative channel that can work with a worldview or the explicit empty-text route from `ZF-ComfyUI-Helper`.
- Defensive handling for incomplete VLM JSON and accidental source-image text leakage.
- Editable JSON catalogs for purposes, visual methods, worldviews, defaults, and writing grammar.

## Recommended Reference-Creativity Flow

```text
LoadImage
  -> ZF Image Reference Analyzer.analysis_json
  -> ZF Reference Creative Adapter.reference_creative_json
  -> ZF Prompt Director.reference_creative_json

Worldview / empty text -> ZF Prompt Director.theme
User prompt            -> ZF Prompt Director.user_prompt
EmptyLatentImage       -> KSampler.latent_image
```

For semantic creativity transfer, do not connect the source image VAE latent to the sampler and do not connect `reference_image` unless you intentionally want IP-Adapter, ControlNet, or image-to-image structure control.

## Installation

Clone the repository into ComfyUI's `custom_nodes` directory:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/Z-yaofang/ZF-ComfyUI-PromptDirector.git
```

Restart ComfyUI and refresh the browser.

The core prompt-director nodes use only ComfyUI-provided Python packages. The built-in reference-image analyzer is optional and requires an installed llama.cpp multimodal custom node that provides `LLAMACPPMODEL` and `LLAMACPPARAMS`. Alternatively, connect an existing VLM text result to `analysis_result`.

`ZF-ComfyUI-Helper` is recommended for its dynamic multi-route text switch and explicit empty-text route:

```bash
git clone https://github.com/Z-yaofang/ZF-ComfyUI-Helper.git
```

## Main Nodes

- `ZF Prompt Director V2`
- `ZF Image Reference Analyzer`
- `ZF Reference Creative Adapter`
- `ZF Prompt Organizer and Observer`
- `ZF Prompt Master Switch`

Legacy blueprint/task nodes remain available for workflow compatibility.

## Reference-Image Behavior

- The analyzer requests compact structured JSON and bounds its dedicated analysis temperature to `0.2`.
- If a local VLM stops before closing the JSON object, completed fields are recovered individually.
- Source-image text contributes layout, density, and stroke information but is not copied into the final image prompt unless the user explicitly requests text.
- The reference image acts as a semantic material/creative library. It is not a pixel-copy lock.

## Updating

```bash
cd ComfyUI/custom_nodes/ZF-ComfyUI-PromptDirector
git pull
```

Restart ComfyUI after an update.

## Repository Data

- `data/purposes.json`
- `data/visual_methods.json`
- `data/worldviews.json`
- `data/default_combinations.json`
- `data/writing_grammar.json`

The catalogs can be extended without rewriting the frontend selector.

## License

No open-source license has been selected yet. The repository is public for testing and review; a license can be added later by the repository owner.
