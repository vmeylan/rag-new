import json
import logging
from datetime import datetime

from llama_index.callbacks.base_handler import BaseCallbackHandler
from llama_index.callbacks.schema import CBEventType, EventPayload
from typing import Any, Optional, Dict, List
import os
from llama_index.llms import MessageRole
from llama_index.prompts.chat_prompts import TEXT_QA_SYSTEM_PROMPT

from src.Llama_index_sandbox import root_dir
from src.Llama_index_sandbox.prompts import QUERY_ENGINE_TOOL_ROUTER


class JSONLoggingHandler(BaseCallbackHandler):

    logs = []

    def __init__(self, event_starts_to_ignore: List[CBEventType], event_ends_to_ignore: List[CBEventType]):
        super().__init__(event_starts_to_ignore, event_ends_to_ignore)

        if not os.path.exists(f"{root_dir}/logs/json"):
            os.makedirs(f"{root_dir}/logs/json")
        self.log_file = f"{root_dir}/logs/json/{datetime.now().strftime('%Y-%m-%d_%H:%M:%S')}.log"

        self.current_section = None  # This will point to the part of the log we are currently writing to.
        self.current_logs = []  # Keep all current logs in memory for rewriting.
        with open(self.log_file, 'w') as log:
            json.dump(self.current_logs, log)  # Initialize file with an empty list.

    def on_event_start(self, event_type: CBEventType, payload: Optional[Dict[str, Any]] = None, event_id: str = "", parent_id: str = "", **kwargs: Any):
        entry = {}
        if event_type == CBEventType.LLM:
            messages = payload.get(EventPayload.MESSAGES, []) if payload else []
            serialized = payload.get(EventPayload.SERIALIZED, {}) if payload else {}

            if messages[-1].role == MessageRole.USER:
                message_content = messages[-1].content
                if QUERY_ENGINE_TOOL_ROUTER in message_content:
                    user_raw_input = message_content.replace(f"\n{QUERY_ENGINE_TOOL_ROUTER}", "")
                    entry = {
                        "event_type": event_type,
                        "model_params": serialized,
                        "user_raw_input": user_raw_input,
                        "LLM_input": message_content,
                    }
                elif "Context information is below." in message_content:
                    assert TEXT_QA_SYSTEM_PROMPT.content in messages[0].content, "The first message should be the system prompt."
                    tool_output = message_content
                    entry = {
                        "event_type": event_type,
                        "tool_output": tool_output,
                    }
                else:
                    retrieved_context, previous_answer = self.parse_message_content(message_content)

                    entry = {
                        "event_type": event_type,
                        "retrieved_context": retrieved_context,
                        "previous_answer": previous_answer,
                    }
            else:
                logging.info(f"WARNING: on_event_start: event_type {event_type.name} was not caught by the logging handler.\n")

        elif event_type == CBEventType.FUNCTION_CALL:
            function_call = {"function_call": []}
            self.append_to_last_log_entry(function_call)
            self.current_section = function_call["function_call"]

        elif event_type == CBEventType.TEMPLATING:
            if payload:
                template_vars = payload.get(EventPayload.TEMPLATE_VARS, {})
                template = payload.get(EventPayload.TEMPLATE, "")
                entry = {"event_type": event_type, "instructions": template, "retrieved_chunk": template_vars}
        else:
            logging.info(f"WARNING: on_event_start: event_type {event_type.name} was not caught by the logging handler.\n")

        if entry.keys():
            entry["event_type"] = entry["event_type"] + " start"

        self.log_entry(entry=entry)
        # Other event types can be added with elif clauses here...

    def log_entry(self, entry):
        """
        Add a new log entry in the current section. If we are within a function call, the entry is nested appropriately.
        """
        if entry.keys():
            if self.current_section is not None:
                # We are inside a nested section, so we should add the log entry here.
                self.current_section.append(entry)
            else:
                # We are not in a nested section, so this entry goes directly under the main log list.
                self.current_logs.append(entry)

        self.rewrite_log_file()  # Update the log file with the new entry.

    def append_to_last_log_entry(self, additional_content):
        """
        Append new content to the last log entry without overwriting existing information.
        This handles both the main log and nested sections.
        """
        if self.current_section is not None:
            # We're inside a nested section, so the last entry should be here.
            target_section = self.current_section
        else:
            # We're not inside a nested section, so the last entry should be in the main log.
            target_section = self.current_logs

        if target_section:
            # Ensure the last log entry is a list where we can append new dictionaries.
            last_log_entry = target_section[-1]

            if isinstance(last_log_entry, list):
                # Append the new content as a separate dictionary within the list.
                last_log_entry.append(additional_content)
            elif isinstance(last_log_entry, dict):
                # If the last entry is a dictionary, we need to decide how to handle it.
                # For example, you could add a new key-value pair where the value is your new content.
                # Here, we're assuming there's a specific key under which content should be added.
                content_key = "additional_content"  # Replace with your actual key.

                # Check if this key already exists and whether its value is a list.
                if content_key in last_log_entry:
                    if isinstance(last_log_entry[content_key], list):
                        # Append the new content to the existing list.
                        last_log_entry[content_key].append(additional_content)
                    else:
                        # If it's not a list, you need to decide how you want to handle it.
                        # You could raise an error, convert it into a list, etc.
                        raise TypeError(f"Expected a list for '{content_key}' but got {type(last_log_entry[content_key])}.")
                else:
                    # If the key doesn't exist, create it and set its value to a list containing your new content.
                    last_log_entry[content_key] = [additional_content]
            else:
                raise TypeError("The last log entry is neither a list nor a dictionary and cannot be appended to.")

            self.rewrite_log_file()  # Update the log file with the new content.
        else:
            # Handle the case where there's no suitable target section to append to.
            raise ValueError("No target section available to append new content.")

    def on_event_end(self, event_type: CBEventType, payload: Optional[Dict[str, Any]] = None, event_id: str = "", parent_id: str = "", **kwargs: Any):
        entry = {}

        if event_type == CBEventType.LLM and payload:
            messages = payload.get(EventPayload.MESSAGES, [])
            response = payload.get(EventPayload.RESPONSE, {})
            if response.message.role == MessageRole.ASSISTANT and response.message.content.startswith("Thought: I need to use a tool to help me answer the question."):
                LLM_response = response.message.content
                # self.append_to_last_log_entry({"LLM_response": LLM_response})
                entry = {"event_type": event_type, "LLM_response": LLM_response}

            elif response.message.role == MessageRole.ASSISTANT and response.message.content.startswith("Thought: I can answer without using any more tools."):
                entry = {"event_type": event_type, "LLM_response": response.message.content, "subjective grade from 1 to 10": ""}

            elif response.message.role == MessageRole.ASSISTANT:  # catch-all
                entry = {"event_type": event_type, "LLM_response": response.message.content, "subjective grade from 1 to 10": ""}
            else:
                logging.info(f"WARNING: on_event_end: event_type {event_type.name} was not caught by the logging handler.\n")

        elif event_type == CBEventType.FUNCTION_CALL:
            self.current_section = None
            entry = {"event_type": event_type, "tool_output": payload.get(EventPayload.FUNCTION_OUTPUT, "")}

        elif event_type == CBEventType.TEMPLATING:
            pass

        else:
            logging.info(f"WARNING: on_event_end: event_type {event_type.name} was not caught by the logging handler.\n")

        if entry.keys():
            entry["event_type"] = entry["event_type"] + " end"
        self.log_entry(entry=entry)

    def parse_message_content(self, message_content):
        """
        Parse the message content to retrieve 'retrieved_context' and 'previous_answer'.
        This function assumes 'message_content' is a string where the context and answer are
        separated by known delimiter strings.
        """

        # Define your delimiters
        context_start_delim = "New Context:"
        context_end_delim = "Query:"
        answer_start_delim = "Original Answer:"
        answer_end_delim = "New Answer:"
        if "Observation:" in message_content:
            return None, None
        # Find the indices of your delimiters
        try:
            context_start = message_content.index(context_start_delim) + len(context_start_delim)
            context_end = message_content.index(context_end_delim)

            answer_start = message_content.index(answer_start_delim) + len(answer_start_delim)
            answer_end = message_content.index(answer_end_delim)

            # Extract the content based on the indices of the delimiters
            retrieved_context = message_content[context_start:context_end].strip()
            previous_answer = message_content[answer_start:answer_end].strip()
            # TODO 2023-10-20: investigate why we cant always parse the above successfully
            # Return the extracted information
            return retrieved_context, previous_answer

        except ValueError as e:
            # Handle the case where the delimiters aren't found in the message content
            logging.warning(f"parse_message_content: Error parsing message content: {e}")
            return None, None  # or handle this in a way appropriate for your application

    def rewrite_log_file(self):
        # A helper method to handle writing the logs to the file.
        with open(self.log_file, 'w') as log:  # Note the 'w' here; we're overwriting the file.
            json.dump(self.current_logs, log, indent=4)  # Pretty-print for readability.

    def start_trace(self, trace_id: Optional[str] = None) -> None:
        """Not implemented."""

    def end_trace(
        self,
        trace_id: Optional[str] = None,
        trace_map: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        """Not implemented."""
