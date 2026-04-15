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

""" Invoke methods for image generation """

import json
import uuid
import base64
from datetime import datetime

from pylon.core.tools import log  # pylint: disable=E0611,E0401,W0611
from pylon.core.tools import web  # pylint: disable=E0611,E0401,W0611

from ..utils.elitea_client_mini import EliteAClientMini


class Method:  # pylint: disable=E1101,R0903,W0201
    """
        Method Resource

        self is pointing to current Module instance

        web.method decorator takes zero or one argument: method name
        Note: web.method decorator must be the last decorator (at top)
    """

    @web.method()
    def validate_invoke_request(self, toolkit_name, tool_name, request_data):
        """ Invoke: validate request parameters """
        #
        # Check toolkit/tool
        #
        if toolkit_name not in ["ImageGen"] or tool_name not in ["generate_image", "edit_image"]:
            return {
                "errorCode": "404",
                "message": "Resource Not Found",
                "details": [f"Unknown toolkit '{toolkit_name}' or tool '{tool_name}'"],
            }, 404
        #
        # Check params
        #
        toolkit_params = request_data.get("configuration", {}).get("parameters", {})
        tool_params = request_data.get("parameters", {})
        #
        params = toolkit_params.copy()
        for key, value in tool_params.items():
            if key not in params or value:
                params[key] = value
        #
        # Required parameters (common)
        #
        required_params = ["llm_settings", "image_generation_model"]
        #
        # Tool-specific required parameters
        #
        if tool_name == "generate_image":
            required_params.append("prompt")
        elif tool_name == "edit_image":
            required_params.extend(["prompt", "source_filepath"])
        #
        for key in required_params:
            if key not in params:
                return {
                    "errorCode": "400",
                    "message": "Bad Request",
                    "details": [f"Missing required parameter: {key}"],
                }, 400
        #
        # Check that llm_settings contains project_id for artifact storage
        #
        llm_settings = params.get("llm_settings", {})
        if not llm_settings.get("project_id"):
            return {
                "errorCode": "400",
                "message": "Bad Request",
                "details": ["llm_settings.project_id is required for artifact storage"],
            }, 400
        #
        return None

    @web.method()
    def perform_invoke_request(self, toolkit_name, tool_name, request_data):  # pylint: disable=R0912,R0914,R0915
        """
        Invoke: perform image generation/editing and save artifacts

        Uses EliteAClientMini to:
        1. Generate/edit images via AI model
        2. Save each image as artifact in storage bucket
        3. Return artifact metadata (NO base64 over network!)

        provider_worker receives artifact IDs and emits file_modified events.
        """
        #
        # Default bucket from config (used as fallback)
        #
        default_bucket = self.descriptor.config.get("image_bucket", "imagelibrary")
        #
        try:
            #
            # Extract parameters
            #
            toolkit_params = request_data.get("configuration", {}).get("parameters", {})
            tool_params = request_data.get("parameters", {})
            #
            params = toolkit_params.copy()
            for key, value in tool_params.items():
                if key not in params or value:
                    params[key] = value
            #
            # Image generation model from toolkit settings
            #
            model_image_generation = params["image_generation_model"]
            #
            # Bucket from toolkit settings (with fallback to config default)
            #
            image_bucket = params.get("bucket") or default_bucket
            #
            # Optional name_prefix for folder isolation or flat naming
            #
            name_prefix = params.get("name_prefix") or ""
            #
            # LLM settings for API access
            # Use new normalized field names (api_base, api_key) from provider_worker
            #
            llm_settings = params["llm_settings"]
            api_base = llm_settings.get("api_base", "")
            api_key = llm_settings.get("api_key", "")
            model_timeout = llm_settings.get("model_timeout", 600)
            project_id = llm_settings.get("project_id")
            #
            if not api_base:
                return _make_error_result(
                    "api_base is required in llm_settings"
                )
            #
            # Initialize EliteAClientMini
            # Strip LLM path suffix from api_base to get base URL
            #
            base_url = api_base.rstrip('/')
            for suffix in ['/llm/v1', '/v1', '/llm']:
                if base_url.endswith(suffix):
                    base_url = base_url[:-len(suffix)]
                    break
            #
            client = EliteAClientMini(
                base_url=base_url,
                project_id=project_id,
                auth_token=api_key,
                model_image_generation=model_image_generation,
                image_bucket=image_bucket,
                model_timeout=model_timeout,
            )
            #
            # Ensure bucket exists
            #
            if not client.ensure_bucket_exists(image_bucket):
                log.warning("ImageGen: Could not ensure bucket '%s' exists", image_bucket)
            #
            # Route to appropriate handler based on tool_name
            #
            if tool_name == "generate_image":
                return self._perform_generate_image(client, params, image_bucket, model_image_generation, name_prefix)
            elif tool_name == "edit_image":
                return self._perform_edit_image(client, params, image_bucket, model_image_generation, name_prefix)
            else:
                return _make_error_result(f"Unknown tool: {tool_name}")
            #
        except ValueError as e:
            log.error("ImageGen: Validation error: %s", str(e))
            return _make_error_result(str(e))
        except Exception as e:  # pylint: disable=W0718
            log.exception("ImageGen: Unexpected error during image operation")
            return _make_error_result(f"Unexpected error: {str(e)}")

    @web.method()
    def _perform_generate_image(self, client, params, image_bucket, model_image_generation, name_prefix=""):  # pylint: disable=R0914
        """
        Perform image generation.
        
        Args:
            client: EliteAClientMini instance
            params: Merged parameters from toolkit and tool
            image_bucket: Target bucket for artifacts
            model_image_generation: Model name for logging
            name_prefix: Raw prefix prepended to filenames
            
        Returns:
            dict with invocation result
        """
        #
        # Tool parameters
        #
        prompt = params["prompt"]
        filename = params.get("filename", "image")
        n = params.get("n", 1)
        size = params.get("size", "auto")
        quality = params.get("quality", "auto")
        style = params.get("style")
        #
        # Generate images
        #
        log.info(
            "ImageGen: Generating %d image(s) with model %s, prompt: %s...",
            n, model_image_generation, prompt[:50]
        )
        #
        result_data = client.generate_image(
            prompt=prompt,
            n=n,
            size=size,
            quality=quality,
            style=style,
        )
        #
        # Process and save images
        #
        return self._process_and_save_images(
            client=client,
            result_data=result_data,
            image_bucket=image_bucket,
            filename=filename,
            prompt=prompt,
            model=model_image_generation,
            size=size,
            quality=quality,
            operation="generated",
            name_prefix=name_prefix,
        )

    @web.method()
    def _perform_edit_image(self, client, params, image_bucket, model_image_generation, name_prefix=""):  # pylint: disable=R0914
        """
        Perform image editing.
        
        Args:
            client: EliteAClientMini instance
            params: Merged parameters from toolkit and tool
            image_bucket: Target bucket for artifacts
            model_image_generation: Model name for logging
            name_prefix: Raw prefix prepended to filenames
            
        Returns:
            dict with invocation result
        """
        #
        # Tool parameters
        #
        prompt = params["prompt"]
        source_filepath = params["source_filepath"]
        mask_filepath = params.get("mask_filepath")
        filename = params.get("filename", "edited_image")
        n = params.get("n", 1)
        size = params.get("size", "auto")
        quality = params.get("quality", "auto")
        #
        # Download source image
        #
        log.info("ImageGen: Downloading source file %s", source_filepath)
        source_image_data = client.download_artifact_by_filepath(source_filepath)
        #
        if not source_image_data:
            return _make_error_result(
                f"Failed to download source image: {source_filepath}"
            )
        #
        # Download mask if provided
        #
        mask_data = None
        if mask_filepath:
            log.info("ImageGen: Downloading mask file %s", mask_filepath)
            mask_data = client.download_artifact_by_filepath(mask_filepath)
            if not mask_data:
                return _make_error_result(
                    f"Failed to download mask file: {mask_filepath}"
                )
        #
        # Edit image
        #
        log.info(
            "ImageGen: Editing image with model %s, prompt: %s...",
            model_image_generation, prompt[:50]
        )
        #
        result_data = client.edit_image(
            prompt=prompt,
            image_data=source_image_data,
            mask_data=mask_data,
            n=n,
            size=size,
            quality=quality,
        )
        #
        # Process and save images
        #
        return self._process_and_save_images(
            client=client,
            result_data=result_data,
            image_bucket=image_bucket,
            filename=filename,
            prompt=prompt,
            model=model_image_generation,
            size=size,
            quality=quality,
            operation="edited",
            source_filepath=source_filepath,
            name_prefix=name_prefix,
        )

    @web.method()
    def _process_and_save_images(  # pylint: disable=R0913,R0914
        self,
        client,
        result_data,
        image_bucket,
        filename,
        prompt,
        model,
        size,
        quality,
        operation,
        source_filepath=None,
        name_prefix="",
    ):
        """
        Process API response and save images as artifacts.
        
        Args:
            client: EliteAClientMini instance
            result_data: API response with image data
            image_bucket: Target bucket
            filename: Base filename
            prompt: Original prompt
            model: Model name
            size: Image size
            quality: Image quality
            operation: 'generated' or 'edited' for logging
            source_filepath: Original file path (for edit operations)
            name_prefix: Raw prefix prepended to filenames
            
        Returns:
            dict with invocation result
        """
        #
        if "data" not in result_data:
            return _make_error_result(
                f"Unexpected response format: {result_data}"
            )
        #
        images = result_data["data"]
        result_objects = []
        saved_count = 0
        #
        # Save each image as artifact
        #
        for idx, image_data in enumerate(images, 1):
            b64_json = image_data.get("b64_json")
            if not b64_json:
                log.warning("ImageGen: Image %d has no b64_json data", idx)
                continue
            #
            # Generate unique filename with timestamp, apply name_prefix
            #
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")[:-3]
            base_name = f"{filename}_{timestamp}.png"
            image_filename = f"{name_prefix}{base_name}" if name_prefix else base_name
            #
            # Decode base64 to binary
            #
            try:
                binary_data = base64.b64decode(b64_json)
            except Exception as decode_err:  # pylint: disable=W0718
                log.error("ImageGen: Failed to decode base64 for image %d: %s", idx, decode_err)
                continue
            #
            # Save artifact
            #
            artifact_result = client.create_artifact(
                bucket_name=image_bucket,
                artifact_name=image_filename,
                artifact_data=binary_data,
            )
            #
            if "error" in artifact_result:
                log.error(
                    "ImageGen: Failed to save artifact %s: %s",
                    image_filename, artifact_result["error"]
                )
                continue
            #
            # Get filepath from response or construct it manually as fallback
            new_filepath = artifact_result.get("filepath")
            if not new_filepath:
                new_filepath = f"/{image_bucket}/{image_filename}"
            #
            log.info(
                "ImageGen: Saved artifact %s at %s",
                image_filename, new_filepath
            )
            #
            # Build metadata
            #
            meta = {
                "prompt": prompt,
                "image_number": idx,
                "model": model,
                "size": size,
                "quality": quality,
            }
            if source_filepath:
                meta["source_filepath"] = source_filepath
            #
            # Add artifact info to result (NO base64!)
            #
            result_objects.append({
                "object_type": "image",
                "filepath": new_filepath,
                "meta": meta
            })
            saved_count += 1
        #
        # Add summary message at the beginning
        #
        result_objects.insert(0, {
            "object_type": "message",
            "data": (
                f"{operation.capitalize()} and saved {saved_count} image(s) successfully. "
                "Note: filepath is an internal storage path, not a URL — do not construct links from it."
            )
        })
        #
        log.info("ImageGen: Successfully %s and saved %d images", operation, saved_count)
        #
        return {
            "invocation_id": str(uuid.uuid4()),
            "status": "Completed",
            "result": json.dumps(result_objects)
        }


def _make_error_result(message):
    """ Create error result in expected format """
    return {
        "invocation_id": str(uuid.uuid4()),
        "status": "Failed",
        "result": json.dumps([{
            "object_type": "message",
            "data": f"Error: {message}"
            }])
        }
