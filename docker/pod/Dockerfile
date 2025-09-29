FROM runpod/pytorch:2.8.0-py3.11-cuda12.8.1-cudnn-devel-ubuntu22.04

RUN apt-get update && \
    apt-get install -y --no-install-recommends docker.io && \
    rm -rf /var/lib/apt/lists/*

ENV JUPYTER_TOKEN=''
ENV JUPYTER_PASSWORD=''    
# COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
# RUN chmod +x /usr/local/bin/docker-entrypoint.sh
# ENTRYPOINT ["/opt/nvidia/nvidia_entrypoint.sh"]
# ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["/start.sh"]