import os
import json
from typing import Any, Dict, List

import requests

from .base import BatchProvider


class HuggingFaceProvider(BatchProvider):
    """
    Provider for HuggingFace Inference API batch jobs.

    The provider communicates with the generic HuggingFace batch endpoint
    ``https://api.huggingface.co/batch``.  Authentication is performed via the
    ``HF_API_KEY`` environment variable which must be set before using the
    provider.

    The expected payload format for a batch request is::

        {
            "model": "<model-id>",
            "inputs": [{...}, {...}, ...]
        }

    The API returns a JSON object containing a ``batch_id`` that can be used
    to retrieve status and results.
    """

    _BASE_URL = "https://api.huggingface.co/batch"

    def __init__(self) -> None:
        """
        Initialise the provider and verify that the required API key is present.

        Raises:
            RuntimeError: If ``HF_API_KEY`` is not defined in the environment.
        """
        self.api_key = os.getenv("HF_API_KEY")
        if not self.api_key:
            raise RuntimeError("Environment variable HF_API_KEY is required for HuggingFaceProvider.")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def create_batch(self, model: str, inputs: List[Dict[str, Any]]) -> str:
        """
        Submit a new batch job to HuggingFace.

        Args:
            model: The identifier of the HuggingFace model to invoke (e.g. ``"gpt2"``).
            inputs: A list of input dictionaries as required by the model.

        Returns:
            The ``batch_id`` string assigned by the HuggingFace service.

        Raises:
            RuntimeError: If the request fails or the response does not contain a batch ID.
        """
        payload = self.build_request(model, inputs)
        response = requests.post(self._BASE_URL, headers=self.headers, json=payload)
        if response.status_code != 200:
            raise RuntimeError(f"Failed to create batch: {response.status_code} {response.text}")

        data = response.json()
        batch_id = data.get("batch_id")
        if not batch_id:
            raise RuntimeError("Response from HuggingFace missing 'batch_id'.")
        return batch_id

    def retrieve_batch(self, batch_id: str) -> Dict[str, Any]:
        """
        Retrieve the current status of a batch job.

        Args:
            batch_id: The identifier returned by :meth:`create_batch`.

        Returns:
            A dictionary representing the batch status as returned by the API.

        Raises:
            RuntimeError: If the request fails.
        """
        url = f"{self._BASE_URL}/{batch_id}"
        response = requests.get(url, headers=self.headers)
        if response.status_code != 200:
            raise RuntimeError(f"Failed to retrieve batch {batch_id}: {response.status_code} {response.text}")
        return response.json()

    def get_results(self, batch_id: str) -> List[Dict[str, Any]]:
        """
        Fetch the results of a completed batch job.

        Args:
            batch_id: The identifier of the batch job.

        Returns:
            A list of result dictionaries, one per input item.

        Raises:
            RuntimeError: If the request fails or the batch is not yet completed.
        """
        url = f"{self._BASE_URL}/{batch_id}/results"
        response = requests.get(url, headers=self.headers)
        if response.status_code != 200:
            raise RuntimeError(f"Failed to get results for batch {batch_id}: {response.status_code} {response.text}")

        data = response.json()
        results = data.get("results")
        if results is None:
            raise RuntimeError(f"Results not found in response for batch {batch_id}.")
        return results

    def build_request(self, model: str, inputs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Construct the JSON payload for a batch request.

        Args:
            model: The HuggingFace model identifier.
            inputs: A list of input dictionaries.

        Returns:
            A dictionary ready to be JSON‑encoded and sent to the API.
        """
        return {
            "model": model,
            "inputs": inputs,
        }
