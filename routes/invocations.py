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

""" Invocations status routes """

import flask  # pylint: disable=E0401

from pylon.core.tools import log  # pylint: disable=E0611,E0401,W0611
from pylon.core.tools import web  # pylint: disable=E0611,E0401,W0611


class Route:  # pylint: disable=E1101,R0903
    """ Route """

    @web.route("/tools/<toolkit_name>/<tool_name>/invocations/<invocation_id>", methods=["GET", "DELETE"])  # pylint: disable=C0301
    def invocations_route(self, toolkit_name, tool_name, invocation_id):  # pylint: disable=R0911
        """ Handler for invocation status check and cancellation """
        if flask.request.method == "GET":
            with self.state_lock:
                if toolkit_name not in self.invocation_state:
                    return {
                        "errorCode": "404",
                        "message": "Resource Not Found",
                        "details": [f"Unknown toolkit: {toolkit_name}"],
                    }, 404
                #
                if tool_name not in self.invocation_state[toolkit_name]:
                    return {
                        "errorCode": "404",
                        "message": "Resource Not Found",
                        "details": [f"Unknown tool: {tool_name}"],
                    }, 404
                #
                if invocation_id not in self.invocation_state[toolkit_name][tool_name]:
                    return {
                        "errorCode": "404",
                        "message": "Resource Not Found",
                        "details": [f"Unknown invocation: {invocation_id}"],
                    }, 404
                #
                invocation_state = self.invocation_state[toolkit_name][tool_name][invocation_id]
                invocation_status = invocation_state.get("status", "unknown")
                #
                custom_events = {}
                #
                if "custom_events" in invocation_state and invocation_state["custom_events"]:
                    custom_events["custom_events"] = invocation_state["custom_events"].copy()
                    invocation_state["custom_events"].clear()
                #
                if invocation_status == "pending":
                    return {
                        "invocation_id": invocation_id,
                        "status": "Started",
                        **custom_events,
                    }
                #
                if invocation_status == "running":
                    return {
                        "invocation_id": invocation_id,
                        "status": "InProgress",
                        **custom_events,
                    }
                #
                if invocation_status == "stopped" and "result" in invocation_state:
                    result = invocation_state["result"]
                    #
                    # Handle tuple (response, status_code) format
                    if isinstance(result, tuple) and len(result) == 2:
                        return result[0], result[1]
                    #
                    # Handle dict response
                    if isinstance(result, dict):
                        return {
                            "invocation_id": invocation_id,
                            "status": "Completed",
                            "result": result.get("result", ""),
                            **custom_events,
                        }
                    #
                    return {
                        "invocation_id": invocation_id,
                        "status": "Completed",
                        "result": str(result),
                        **custom_events,
                    }
                #
                # Unknown or transitioning state
                return {
                    "invocation_id": invocation_id,
                    "status": "InProgress",
                    **custom_events,
                }
        #
        elif flask.request.method == "DELETE":
            with self.state_lock:
                if toolkit_name not in self.invocation_state:
                    return {
                        "errorCode": "404",
                        "message": "Resource Not Found",
                        "details": [],
                    }, 404
                #
                if tool_name not in self.invocation_state[toolkit_name]:
                    return {
                        "errorCode": "404",
                        "message": "Resource Not Found",
                        "details": [],
                    }, 404
                #
                if invocation_id not in self.invocation_state[toolkit_name][tool_name]:
                    return {
                        "errorCode": "404",
                        "message": "Resource Not Found",
                        "details": [],
                    }, 404
                #
                invocation_state = self.invocation_state[toolkit_name][tool_name][invocation_id]
                invocation_state["stop_requested"] = True
                #
                log.info("ImageGen: Stop requested for invocation %s", invocation_id)
            #
            return flask.Response(status=204)
        #
        return {
            "errorCode": "500",
            "message": "Internal Server Error",
            "details": [],
        }, 500
