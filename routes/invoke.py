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

""" Invoke route for image generation """

import flask  # pylint: disable=E0401

from pylon.core.tools import log  # pylint: disable=E0611,E0401,W0611
from pylon.core.tools import web  # pylint: disable=E0611,E0401,W0611


class Route:  # pylint: disable=E1101,R0903
    """ Route """

    @web.route("/tools/<toolkit_name>/<tool_name>/invoke", methods=["POST"])
    def invoke_route(self, toolkit_name, tool_name):  # pylint: disable=R0911
        """ Handler for tool invocation """
        #
        # Parse request
        #
        try:
            request_data = flask.request.json
        except:  # pylint: disable=W0702
            return {
                "errorCode": "400",
                "message": "Bad Request",
                "details": ["Invalid JSON in request body"],
            }, 400
        #
        # Validate request
        #
        validation_result = self.validate_invoke_request(toolkit_name, tool_name, request_data)
        if validation_result is not None:
            return validation_result
        #
        # Start task via TaskNode (enables parallel invocations)
        #
        invocation_id = self.invocation_task_node.start_task(
            "perform_invoke_request",
            kwargs={
                "toolkit_name": toolkit_name,
                "tool_name": tool_name,
                "request_data": request_data,
            },
            pool="invocation",
            meta={
                "toolkit_name": toolkit_name,
                "tool_name": tool_name,
            },
        )
        #
        if invocation_id is None:
            return {
                "errorCode": "500",
                "message": "Internal Server Error",
                "details": ["Failed to start invocation task"],
            }, 500
        #
        # Check for async mode
        #
        async_invoke = request_data.get("async", False)
        #
        if async_invoke:
            return {
                "invocation_id": invocation_id,
                "status": "Started",
            }
        #
        # Sync mode: wait for result
        #
        try:
            invoke_result = self.invocation_task_node.join_task(invocation_id)
            return invoke_result
        except BaseException as exception:  # pylint: disable=W0718
            log.exception("Failed to invoke %s:%s", toolkit_name, tool_name)
            exception_info = str(exception)
            #
            return {
                "errorCode": "500",
                "message": "Internal Server Error",
                "details": [exception_info],
            }, 500
