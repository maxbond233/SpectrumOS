# syntax=docker/dockerfile:1
ARG TARGETARCH
FROM scratch AS binary-amd64
ADD --checksum=sha256:53e2a2cb16c5366ea6fbbc479c19ddb4c6a0948273e752f740fb1fbf27bb817c https://github.com/minio/minio/releases/download/RELEASE.2025-04-22T22-12-26Z/minio.linux-amd64.RELEASE.2025-04-22T22-12-26Z /minio

FROM scratch AS binary-arm64
ADD --checksum=sha256:6c2f3142c94240206123177f4ba1e360daa5d1e0a4962e90757ef4f92c3ab57c https://github.com/minio/minio/releases/download/RELEASE.2025-04-22T22-12-26Z/minio.linux-arm64.RELEASE.2025-04-22T22-12-26Z /minio

FROM binary-${TARGETARCH} AS binary
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home minio && mkdir /data && chown minio:minio /data
COPY --from=binary --chmod=755 /minio /usr/local/bin/minio
USER minio
HEALTHCHECK --interval=3s --timeout=3s --retries=20 CMD curl --fail http://localhost:9000/minio/health/live
ENTRYPOINT ["minio"]
