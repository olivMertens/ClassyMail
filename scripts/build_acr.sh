#!/usr/bin/env bash
set -euo pipefail

ACR_NAME="${ACR_NAME:-}"
IMAGE_NAME="${IMAGE_NAME:-classymail-agent}"
TAG="${TAG:-local}"
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

if [[ "$PUSH_METHOD" == "acr" ]]; then
  echo "[build] Remote build via az acr build -> ${IMAGE}"
  az acr build --registry "$ACR_NAME" --image "$IMAGE_NAME:${TAG}" .
elif [[ "$PUSH_METHOD" == "docker" ]]; then
  echo "[build] Local docker build & push -> ${IMAGE}"
  az acr login -n "$ACR_NAME"
  docker build -t "$IMAGE" .
  docker push "$IMAGE"
else
  echo "Unknown PUSH_METHOD=$PUSH_METHOD (expected acr|docker)" >&2
  exit 1
fi

echo "[ok] Built & pushed ${IMAGE}"
