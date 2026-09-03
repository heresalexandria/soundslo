# Foley-Omni third-party model terms

Foley-Omni is assembled from components with different terms. Soundslo downloads these files at
install time; they are not covered by Soundslo's MIT license.

* Foley-Omni code and the `CocoBro/Foley-Omni` checkpoint repository identify the release as MIT.
* The redistributed Wan2.2 umT5-XXL encoder and tokenizer identify their license as Apache-2.0.
* `mmaudio/ext_weights/v1-16.pth`, `best_netG.pt`, and `synchformer_state_dict.pth` are re-hosted
  from MMAudio. MMAudio publishes its checkpoints under Creative Commons
  Attribution-NonCommercial 4.0 (CC BY-NC 4.0):
  <https://creativecommons.org/licenses/by-nc/4.0/legalcode>.
* `apple/DFN5B-CLIP-ViT-H-14-384` is governed by the Apple Machine Learning Research Model License
  Agreement copied in `APPLE_ML_RESEARCH_MODEL_LICENSE.md`. It is limited to non-commercial
  scientific research and academic development.

The MMAudio and Apple restrictions make Foley-Omni a commercial-release blocker unless the
relevant rights holders relicense the files or those dependencies are replaced. The integration
is intended for local, non-commercial research and personal experimentation.
