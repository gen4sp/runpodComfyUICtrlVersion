docker buildx build --platform linux/amd64 \
 -t gen4sp/runpod-pytorch-docker:latest \
 --push /Users/gen4/Gits/Research/RunPod/runpodComfyuiVersionControl/docker/pod

<!-- build + push -->

docker buildx build --builder runpod-builder \
--platform linux/amd64 \
 -t gen4sp/runpod-pytorch-docker:latest \
 --push .

<!-- check -->

✗ docker buildx inspect --bootstrap
