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

""" Provider descriptor method """

from pylon.core.tools import log  # pylint: disable=E0611,E0401,W0611
from pylon.core.tools import web  # pylint: disable=E0611,E0401,W0611


class Method:  # pylint: disable=E1101,R0903,W0201
    """
        Method Resource

        self is pointing to current Module instance

        web.method decorator takes zero or one argument: method name
        Note: web.method decorator must be the last decorator (at top)
    """

    @web.method()
    def provider_descriptor(self):
        """ Return provider descriptor for toolkit registration """
        service_location_url = self.descriptor.config.get(
            "service_location_url", "http://127.0.0.1:8080"
        )
        image_bucket = self.descriptor.config.get("image_bucket", "imagelibrary")
        #
        return {
            "name": "ImageGenServiceProvider",
            "service_location_url": service_location_url,
            "configuration": {},
            "provided_toolkits": [
                {
                    "name": "ImageGen",
                    "description": "AI image generation toolkit",
                    "toolkit_config": {
                        "type": "ImageGen Configuration",
                        "description": "Configuration for AI image generation.",
                        "fields_order": ["image_generation_model", "bucket", "name_prefix"],
                        "parameters": {
                            "image_generation_model": {
                                "type": "String",
                                "required": True,
                                "description": "Image generation model to use",
                                "json_schema_extra": {
                                    "configuration_model": "image_generation",
                                }
                            },
                            "bucket": {
                                "type": "String",
                                "required": False,
                                "default": image_bucket,
                                "description": "Bucket for storing generated images",
                            },
                            "name_prefix": {
                                "type": "String",
                                "required": False,
                                "default": None,
                                "description": (
                                    "String prefix prepended to generated filenames. "
                                    "Use a trailing slash to place images in a folder "
                                    "(e.g. 'my-folder/'), or any prefix for flat naming "
                                    "(e.g. 'generated-')"
                                ),
                            },
                        },
                    },
                    "provided_tools": [
                        {
                            "name": "generate_image",
                            "args_schema": {
                                "prompt": {
                                    "type": "String",
                                    "required": True,
                                    "description": "Text prompt describing the image to generate",
                                },
                                "filename": {
                                    "type": "String",
                                    "required": False,
                                    "default": "image",
                                    "description": (
                                        "Base filename for the generated image(s) without extension. "
                                        "A timestamp will be appended for uniqueness."
                                    ),
                                },
                                "n": {
                                    "type": "Integer",
                                    "required": False,
                                    "default": 1,
                                    "description": "Number of images to generate (1-10)",
                                },
                                "size": {
                                    "type": "String",
                                    "required": False,
                                    "default": "auto",
                                    "description": "Size of the generated image (e.g., '1024x1024')",
                                },
                                "quality": {
                                    "type": "String",
                                    "required": False,
                                    "default": "auto",
                                    "description": "Quality of the generated image ('low', 'medium', 'high')",
                                },
                                "style": {
                                    "type": "String",
                                    "required": False,
                                    "description": "Style of the generated image (optional)",
                                },
                            },
                            "description": (
                                "Generate images from text prompts using AI models. "
                                f"Images are automatically saved to the '{image_bucket}' bucket. "
                                "Returns artifact info for each generated image."
                            ),
                            "tool_metadata": {
                                "result_composition": "list_of_objects",
                                "result_objects": [
                                    {
                                        "object_type": "message",
                                        "result_target": "response",
                                        "result_encoding": "plain",
                                    },
                                    {
                                        "object_type": "image",
                                        "result_target": "artifact",
                                        "result_extension": "png",
                                        "result_encoding": "base64",
                                        "result_bucket": image_bucket,
                                    },
                                ],
                            },
                            "tool_result_type": "String",
                            "sync_invocation_supported": True,
                            "async_invocation_supported": True,
                        },
                        {
                            "name": "edit_image",
                            "args_schema": {
                                "prompt": {
                                    "type": "String",
                                    "required": True,
                                    "description": "Text prompt describing the desired edit to the image",
                                },
                                "source_filepath": {
                                    "type": "String",
                                    "required": True,
                                    "description": (
                                        "Filepath of the source image to edit in format /{bucket}/{filename}. "
                                        "The image must exist in the artifact storage."
                                    ),
                                },
                                "mask_filepath": {
                                    "type": "String",
                                    "required": False,
                                    "description": (
                                        "Optional filepath of a mask image (PNG with alpha channel) in format /{bucket}/{filename}. "
                                        "Transparent areas indicate where the image should be edited. "
                                        "Not required for GPT Image models which use prompt-based masking."
                                    ),
                                },
                                "filename": {
                                    "type": "String",
                                    "required": False,
                                    "default": "edited_image",
                                    "description": (
                                        "Base filename for the edited image(s) without extension. "
                                        "A timestamp will be appended for uniqueness."
                                    ),
                                },
                                "n": {
                                    "type": "Integer",
                                    "required": False,
                                    "default": 1,
                                    "description": "Number of edited images to generate (1-10)",
                                },
                                "size": {
                                    "type": "String",
                                    "required": False,
                                    "default": "auto",
                                    "description": (
                                        "Size of the output image. Use 'auto' for model default, "
                                        "or specify like '1024x1024', '1536x1024', etc."
                                    ),
                                },
                                "quality": {
                                    "type": "String",
                                    "required": False,
                                    "default": "auto",
                                    "description": (
                                        "Quality of the edited image. "
                                        "Options: 'low', 'medium', 'high', or 'auto'"
                                    ),
                                },
                            },
                            "description": (
                                "Edit an existing image using AI models. "
                                "Provide a source image filepath and a prompt describing the edit. "
                                "Optionally provide a mask filepath for inpainting specific areas. "
                                f"Edited images are saved to the '{image_bucket}' bucket. "
                                "Returns artifact info for each edited image."
                            ),
                            "tool_metadata": {
                                "result_composition": "list_of_objects",
                                "result_objects": [
                                    {
                                        "object_type": "message",
                                        "result_target": "response",
                                        "result_encoding": "plain",
                                    },
                                    {
                                        "object_type": "image",
                                        "result_target": "artifact",
                                        "result_extension": "png",
                                        "result_encoding": "base64",
                                        "result_bucket": image_bucket,
                                    },
                                ],
                            },
                            "tool_result_type": "String",
                            "sync_invocation_supported": True,
                            "async_invocation_supported": True,
                        },
                    ],
                    # Empty toolkit_metadata = appears in toolkit list
                    # (NOT as standalone application)
                    "toolkit_metadata": {},
                },
            ],
        }
