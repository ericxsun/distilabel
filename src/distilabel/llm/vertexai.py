# Copyright 2023-present, Argilla, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from typing import TYPE_CHECKING, List, Optional, Type

from pydantic import PrivateAttr

from distilabel.llm.base import AsyncLLM
from distilabel.utils.logging import get_logger

if TYPE_CHECKING:
    from vertexai.generative_models import (
        Content,
        GenerationConfig,
        GenerativeModel,
        Part,
        SafetySettingsType,
        Tool,
    )

    from distilabel.llm.typing import GenerateOutput
    from distilabel.steps.task.typing import ChatType


def _is_gemini_model(model: str) -> bool:
    """Returns `True` if the model is a model from the Vertex AI Gemini API.

    Args:
        model (str): the model name to be checked.

    Returns:
        bool: `True` if the model is a model from the Vertex AI Gemini API.
    """
    return "gemini" in model


class VertexAILLM(AsyncLLM):
    """VertexAI LLM implementation running the async API clients for Gemini.

    - Gemini API: https://cloud.google.com/vertex-ai/docs/generative-ai/model-reference/gemini

    To use the `VertexAILLM` is necessary to have configured the Google Cloud authentication
    using one of these methods:

    - Setting `GOOGLE_CLOUD_CREDENTIALS` environment variable
    - Using `gcloud auth application-default login` command
    - Using `vertexai.init` function from the `google-cloud-aiplatform` library

    Attributes:
        model: the model name to use for the LLM e.g. "gemini-1.0-pro". [Supported models](https://cloud.google.com/vertex-ai/generative-ai/docs/learn/models).
    """

    model: str
    _aclient: Optional[Type["GenerativeModel"]] = PrivateAttr(...)
    _content_class: Optional[Type["Content"]] = PrivateAttr(...)
    _part_class: Optional[Type["Part"]] = PrivateAttr(...)
    _generation_config_class: Optional["GenerationConfig"] = PrivateAttr(...)
    _logger = PrivateAttr(default=get_logger("llm"))

    def load(self) -> None:
        """Loads the `GenerativeModel` class which has access to `generate_content_async` to benefit from async requests."""

        try:
            from vertexai.generative_models import (
                Content,
                GenerationConfig,
                GenerativeModel,
                Part,
            )

            self._content_class = Content
            self._part_class = Part
            self._generation_config_class = GenerationConfig
        except ImportError as e:
            raise ImportError(
                "vertexai is not installed. Please install it using"
                " `pip install google-cloud-aiplatform`."
            ) from e

        if _is_gemini_model(self.model):
            self._aclient = GenerativeModel(model_name=self.model)
        else:
            raise NotImplementedError(
                "`VertexAILLM` is only implemented for `gemini` models that allow for `ChatType` data."
            )

    @property
    def model_name(self) -> str:
        """Returns the model name used for the LLM."""
        return self.model

    def _chattype_to_content(self, input: "ChatType") -> List["Content"]:
        """Converts a chat type to a list of content items expected by the API.

        Args:
            input: the chat type to be converted.

        Returns:
            List[str]: a list of content items expected by the API.
        """
        contents = []
        for message in input:
            if message["role"] not in ["user", "model"]:
                raise ValueError(
                    "`VertexAILLM only supports the roles 'user' or 'model'."
                )
            contents.append(
                self._content_class(
                    role=message["role"],
                    parts=[self._part_class.from_text(message["content"])],
                )
            )
        return contents

    async def agenerate(  # type: ignore
        self,
        input: "ChatType",
        num_generations: int = 1,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
        stop_sequences: Optional[List[str]] = None,
        safety_settings: Optional["SafetySettingsType"] = None,
        tools: Optional[List["Tool"]] = None,
    ) -> "GenerateOutput":
        """Generates `num_generations` responses for the given input using the [VertexAI async client definition](https://cloud.google.com/vertex-ai/docs/generative-ai/model-reference/gemini).

        Args:
            input: a single input in chat format to generate responses for.
            num_generations: the number of generations to create per input. Defaults to
                `1`.
            temperature: Controls the randomness of predictions. Range: [0.0, 1.0]. Defaults to `None`.
            top_p: If specified, nucleus sampling will be used. Range: (0.0, 1.0]. Defaults to `None`.
            top_k: If specified, top-k sampling will be used. Defaults to `None`.
            max_output_tokens: The maximum number of output tokens to generate per message. Defaults to `None`.
            stop_sequences: A list of stop sequences. Defaults to `None`.
            safety_settings: Safety configuration for returned content from the API. Defaults to `None`.
            tools: A potential list of tools that can be used by the API. Defaults to `None`.

        Returns:
            A list of lists of strings containing the generated responses for each input.
        """
        contents = self._chattype_to_content(input)
        generations = []
        for _ in range(num_generations):
            content = await self._aclient.generate_content_async(
                contents=contents,
                generation_config=self._generation_config_class(
                    candidate_count=1,  # only one candidate allowed per call
                    temperature=temperature,
                    top_k=top_k,
                    top_p=top_p,
                    max_output_tokens=max_output_tokens,
                    stop_sequences=stop_sequences,
                ),
                safety_settings=safety_settings,
                tools=tools,
                stream=False,
            )

            text = None
            try:
                text = content.candidates[0].text
            except ValueError:
                self._logger.warning(
                    f"Received no response using VertexAI client (model: '{self.model}')."
                    f" Finish reason was: '{content.candidates[0].finish_reason}'."
                )
            generations.append(text)

        return generations