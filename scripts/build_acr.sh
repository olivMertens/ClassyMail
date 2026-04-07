#!/usr/bin/env bash
set -euo pipefail

ACR_NAME="${ACR_NAME:-}"
IMAGE_NAME="${IMAGE_NAME:-classymail}"
TAG="${TAG:-$(git rev-parse --short HEAD 2>/dev/null || echo local)}"
REGISTRY="${REGISTRY:-}" # e.g. myacr.azurecr.io
PUSH_METHOD="${PUSH_METHOD:-acr}" # acr|docker

if [[ -z "$ACR_NAME" && -z "$REGISTRY" ]]; then
  echo "ACR_NAME or REGISTRY must be set (e.g. export ACR_NAME=myacr)" >&2
  exit 1
fi

if [[ -z "$REGISTRY" ]]; then
  REGISTRY="${ACR_NAME}.azurecr.io"
fi

IMAGE="${REGISTRY}/${IMAGE_NAME}:${TAG}"
IMAGE_LATEST="${REGISTRY}/${IMAGE_NAME}:latest"

echo ""
echo "[build] ClassyMail ACR Build"
echo "  Image:  ${IMAGE}"
echo "  Method: ${PUSH_METHOD}"
echo ""

if [[ "$PUSH_METHOD" == "acr" ]]; then
  echo "[build] Remote build via ACR Tasks..."
  az acr build \
    --registry "$ACR_NAME" \
    --image "$IMAGE_NAME:${TAG}" \
    --image "$IMAGE_NAME:latest" \
    --platform linux/amd64 \
    --build-arg "COMMIT_SHA=${TAG}" \
    .

  if [[ $? -ne 0 ]]; then
    echo "[build] ACR build failed" >&2
    exit 1
  fi
elif [[ "$PUSH_METHOD" == "docker" ]]; then
  echo "[build] Local docker build & push..."
  az acr login -n "$ACR_NAME"
  docker build -t "$IMAGE" -t "$IMAGE_LATEST" --build-arg "COMMIT_SHA=${TAG}" .
  docker push "$IMAGE"
  docker push "$IMAGE_LATEST"
else
  echo "Unknown PUSH_METHOD=$PUSH_METHOD (expected acr|docker)" >&2
  exit 1
fi

echo ""
echo "[ok] Built & pushed ${IMAGE}"
echo "[ok] Also tagged as ${IMAGE_LATEST}"
