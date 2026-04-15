#!/usr/bin/python3
# coding=utf-8

#   Copyright 2025 EPAM Systems
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

"""
Minimal EliteA client for provider plugins.

Only requires `requests` library (standard pylon dependency).
No langchain, no pydantic - just HTTP calls for image generation and artifact storage.
"""

import mimetypes
import re
import requests
from typing import Optional
from urllib.parse import quote

from pylon.core.tools import log  # pylint: disable=E0611,E0401


class EliteAClientMini:
    """
    Minimal EliteA client for provider plugins.

    Lightweight client for image generation provider. Uses S3 API for
    artifact storage. Only requires ``requests`` (standard pylon dep).
    """

    def __init__(
        self,
        base_url: str,
        project_id: int,
        auth_token: str,
        model_image_generation: str,
        image_bucket: str = "imagelibrary",
        model_timeout: int = 600,
    ):
        """
        Initialize minimal EliteA client.
        
        Args:
            base_url: Base URL of EliteA API (e.g., 'https://elitea.example.com')
            project_id: Project ID for API calls
            auth_token: Bearer token for authentication
            model_image_generation: Model name for image generation (e.g., 'dall-e-3') - REQUIRED
            image_bucket: Default bucket for storing generated images
            model_timeout: Timeout for API calls in seconds
        """
        self.base_url = base_url.rstrip('/')
        self.project_id = project_id
        self.auth_token = auth_token
        self.model_image_generation = model_image_generation
        self.image_bucket = image_bucket
        self.model_timeout = model_timeout

        # Build URLs
        self.image_generation_url = f"{self.base_url}/llm/v1/images/generations"
        self.image_edit_url = f"{self.base_url}/llm/v1/images/edits"
        self.s3_url = f"{self.base_url}/artifacts/s3"

        # Headers
        self.headers = {
            "Authorization": f"Bearer {auth_token}",
        }

    def generate_image(
        self,
        prompt: str,
        n: int = 1,
        size: str = "auto",
        quality: str = "auto",
        response_format: str = "b64_json",
        style: Optional[str] = None,
    ) -> dict:
        """
        Generate images using AI model.
        
        Args:
            prompt: Text prompt describing the image
            n: Number of images to generate (1-10)
            size: Image size (e.g., '1024x1024', or 'auto')
            quality: Image quality ('low', 'medium', 'high', or 'auto')
            response_format: Response format ('b64_json' or 'url')
            style: Optional style parameter
            
        Returns:
            dict with 'data' key containing list of image objects with 'b64_json' key
            
        Raises:
            requests.HTTPError: If API call fails
        """
        image_request_data = {
            "prompt": prompt,
            "model": self.model_image_generation,
            "n": n,
            "response_format": response_format,
        }

        # Only add optional parameters if they have meaningful values
        if size and size.lower() != "auto":
            image_request_data["size"] = size

        if quality and quality.lower() != "auto":
            image_request_data["quality"] = quality

        if style:
            image_request_data["style"] = style

        # Headers for image generation
        headers = self.headers.copy()
        headers["Content-Type"] = "application/json"

        log.info(
            "EliteAClientMini: Generating %d image(s) with model %s, prompt: %s...",
            n, self.model_image_generation, prompt[:50]
        )

        response = requests.post(
            self.image_generation_url,
            headers=headers,
            json=image_request_data,
            verify=False,
            timeout=self.model_timeout,
        )
        if not response.ok:
            msg = self._extract_api_error_message(response)
            raise ValueError(
                f"Image generation failed ({response.status_code}): {msg}"
            )
        return response.json()

    def _s3_params(self) -> dict:
        """Query params required for S3 API authorization."""
        return {"project_id": self.project_id, "format": "json"}

    def create_artifact(
        self,
        bucket_name: str,
        artifact_name: str,
        artifact_data: bytes,
    ) -> dict:
        """
        Upload artifact to S3 storage.

        Args:
            bucket_name: Bucket name (will be lowercased)
            artifact_name: S3 key — may contain folder separators
            artifact_data: Binary data to store

        Returns:
            dict with 'filepath' on success, or 'error' on failure
        """
        sanitized_key, was_modified = self._sanitize_artifact_key(artifact_name)
        if was_modified:
            log.warning(
                "EliteAClientMini: Artifact key sanitized: '%s' -> '%s'",
                artifact_name, sanitized_key
            )

        bucket = bucket_name.lower()
        url = f"{self.s3_url}/{bucket}/{quote(sanitized_key, safe='/')}"

        content_type = mimetypes.guess_type(sanitized_key)[0] or 'application/octet-stream'
        headers = {**self.headers, 'Content-Type': content_type}

        try:
            response = requests.put(
                url,
                headers=headers,
                data=artifact_data,
                params=self._s3_params(),
                verify=False,
                timeout=self.model_timeout,
            )
            if not response.ok:
                return {
                    "error": f"Failed to upload artifact: {response.status_code}",
                    "status_code": response.status_code,
                    "content": response.text,
                }
            return {
                "filepath": f"/{bucket}/{sanitized_key}",
                "bucket": bucket,
                "filename": sanitized_key,
                "size": len(artifact_data),
            }
        except Exception as exc:  # pylint: disable=W0718
            return {"error": str(exc)}

    def bucket_exists(self, bucket_name: str) -> bool:
        """Check if bucket exists via S3 HEAD."""
        try:
            url = f"{self.s3_url}/{bucket_name.lower()}"
            response = requests.head(
                url,
                headers=self.headers,
                params=self._s3_params(),
                verify=False,
                timeout=30,
            )
            return response.status_code == 200
        except Exception:  # pylint: disable=W0718
            return False

    def create_bucket(self, bucket_name: str) -> dict:
        """Create bucket via S3 PUT."""
        url = f"{self.s3_url}/{bucket_name.lower()}"
        response = requests.put(
            url,
            headers=self.headers,
            params=self._s3_params(),
            verify=False,
            timeout=30,
        )
        return self._process_response(response)

    def ensure_bucket_exists(self, bucket_name: str) -> bool:
        """Ensure bucket exists, create if not."""
        if self.bucket_exists(bucket_name):
            return True

        log.info("EliteAClientMini: Creating bucket '%s'", bucket_name)
        result = self.create_bucket(bucket_name)

        if "error" in result:
            log.error("EliteAClientMini: Failed to create bucket: %s", result["error"])
            return False

        return True

    def download_artifact_by_filepath(self, filepath: str) -> Optional[bytes]:
        """
        Download artifact binary content via S3 API.

        Args:
            filepath: Path in format /{bucket}/{key}

        Returns:
            Binary content of the artifact, or None if not found/error
        """
        if not filepath or not filepath.startswith('/'):
            log.error("EliteAClientMini: Invalid filepath format: %s", filepath)
            return None

        parts = filepath[1:].split('/', 1)  # Remove leading slash and split
        if len(parts) != 2:
            log.error("EliteAClientMini: Cannot parse filepath: %s", filepath)
            return None

        bucket, key = parts
        url = f"{self.s3_url}/{bucket.lower()}/{quote(key, safe='/')}"

        try:
            response = requests.get(
                url,
                headers=self.headers,
                params=self._s3_params(),
                verify=False,
                timeout=self.model_timeout,
            )

            if response.status_code == 404:
                log.warning("EliteAClientMini: Artifact at %s not found", filepath)
                return None

            response.raise_for_status()
            return response.content

        except Exception as e:  # pylint: disable=W0718
            log.error("EliteAClientMini: Failed to download artifact %s: %s", filepath, e)
            return None

    def edit_image(
        self,
        prompt: str,
        image_data: bytes,
        image_filename: str = "image.png",
        mask_data: Optional[bytes] = None,
        mask_filename: str = "mask.png",
        n: int = 1,
        size: str = "auto",
        quality: str = "auto",
        response_format: str = "b64_json",
    ) -> dict:
        """
        Edit images using AI model.
        
        Uses multipart/form-data format as required by the image edit API.
        Model-specific parameter validation is handled by LiteLLM.
        
        Args:
            prompt: Text prompt describing the desired edit
            image_data: Binary data of the source image to edit
            image_filename: Filename for the source image
            mask_data: Optional binary data for mask image (PNG with alpha channel)
            mask_filename: Filename for the mask image
            n: Number of edited images to generate (1-10)
            size: Image size (e.g., '1024x1024', or 'auto')
            quality: Image quality ('low', 'medium', 'high', or 'auto')
            response_format: Response format ('b64_json' or 'url')
            
        Returns:
            dict with 'data' key containing list of image objects with 'b64_json' key
            
        Raises:
            requests.HTTPError: If API call fails
            
        Note:
            TODO: Add image size/format validation (50MB limit for GPT models,
            4MB for DALL-E 2, mask must match source dimensions)
        """
        # Build multipart form data
        # File tuple format: (field_name, (filename, file_data, content_type))
        # FastAPI expects 'image' field name for List[UploadFile]
        files = [
            ('image', (image_filename, image_data, 'image/png')),
        ]
        
        if mask_data:
            files.append(('mask', (mask_filename, mask_data, 'image/png')))
        
        # Form data (non-file fields) as regular dict
        # Note: response_format is not supported by all providers (e.g., Azure)
        # We rely on the default being b64_json for most providers
        form_data = {
            'prompt': prompt,
            'model': self.model_image_generation,
            'n': str(n),
        }
        
        # Only add optional parameters if they have meaningful values
        if size and size.lower() != "auto":
            form_data['size'] = size
            
        if quality and quality.lower() != "auto":
            form_data['quality'] = quality

        log.info(
            "EliteAClientMini: Editing image with model %s, prompt: %s...",
            self.model_image_generation, prompt[:50]
        )
        log.debug(
            "EliteAClientMini: Edit request to %s, form_data: %s, files count: %d",
            self.image_edit_url, list(form_data.keys()), len(files)
        )

        # Use separate files and data parameters
        # Don't set Content-Type header - requests will set multipart boundary automatically
        headers = {"Authorization": self.headers["Authorization"]}
        
        response = requests.post(
            self.image_edit_url,
            headers=headers,
            files=files,
            data=form_data,
            verify=False,
            timeout=self.model_timeout,
        )
        if not response.ok:
            msg = self._extract_api_error_message(response)
            raise ValueError(
                f"Image edit failed ({response.status_code}): {msg}"
            )
        return response.json()

    @staticmethod
    def _extract_api_error_message(response) -> str:
        """Extract human-readable error message from API error response."""
        try:
            body = response.json()
            message = body.get("error", {}).get("message", "")
            if message:
                # LiteLLM wraps inner JSON: "litellm.BadRequestError: OpenAIException - {...}"
                # Try to extract the inner error message
                import json as _json
                brace = message.find("{")
                end_brace = message.rfind("}")
                if brace != -1 and end_brace > brace:
                    try:
                        inner = _json.loads(message[brace:end_brace + 1])
                        inner_msg = inner.get("error", {}).get("message", "")
                        if inner_msg:
                            return inner_msg
                    except (ValueError, KeyError):
                        pass
                return message
        except Exception:  # pylint: disable=W0718
            pass
        # Fallback to raw response text
        return response.text or f"HTTP {response.status_code}"

    @staticmethod
    def _sanitize_segment(segment: str) -> str:
        """Sanitize a single path segment (filename or folder name)."""
        if not segment or not segment.strip():
            return "unnamed"
        cleaned = re.sub(r'[^\w\s.-]', '', segment, flags=re.UNICODE)
        cleaned = re.sub(r'[-\s]+', '-', cleaned)
        cleaned = cleaned.strip('-').strip()
        return cleaned or "unnamed"

    @classmethod
    def _sanitize_artifact_key(cls, key: str) -> tuple:
        """
        Sanitize S3 key that may contain folder separators.

        Handles paths like ``folder/subfolder/image.png``.
        Blocks directory traversal (``..``).

        Returns:
            Tuple of (sanitized_key, was_modified)
        """
        if not key or not key.strip():
            return "unnamed_file", True

        original = key
        # Block traversal
        key = key.replace('..', '')
        # Normalize separators, strip leading/trailing slashes
        key = key.replace('\\', '/')
        key = key.strip('/')

        parts = key.split('/')
        sanitized_parts = []
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                # Last part is the filename — preserve extension
                dot_idx = part.rfind('.')
                if dot_idx > 0:
                    name = cls._sanitize_segment(part[:dot_idx])
                    ext = re.sub(r'[^\w.]', '', part[dot_idx:], flags=re.UNICODE)
                    sanitized_parts.append(f"{name}{ext}")
                else:
                    sanitized_parts.append(cls._sanitize_segment(part))
            else:
                sanitized_parts.append(cls._sanitize_segment(part))

        sanitized = '/'.join(p for p in sanitized_parts if p)
        if not sanitized:
            sanitized = "unnamed_file"
        return sanitized, (sanitized != original)

    @staticmethod
    def _process_response(response: requests.Response) -> dict:
        """
        Process HTTP response into standard format.
        
        Args:
            response: requests.Response object
            
        Returns:
            dict with response data or error info
        """
        if response.status_code == 403:
            return {"error": "You are not authorized to access this resource"}
        elif response.status_code == 404:
            return {"error": "Resource not found"}
        elif response.status_code != 200:
            return {
                "error": "An error occurred",
                "status_code": response.status_code,
                "content": response.text,
            }
        else:
            return response.json()
