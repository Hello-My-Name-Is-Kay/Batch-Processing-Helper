import os
from typing import Any, Dict, List

import requests

from .base import BatchProvider


class FireworksProvider(BatchProvider):
    """
    Fireworks AI batch provider implementation.

    This provider interacts with the Fireworks AI batch inference API.
    It creates a batch job, retrieves its status, and fetches the results.

    Environment Variables
    ---------------------
    - ``FIREWORKS_API_KEY``: API key used for authentication. Must be set
      in the environment before using the provider.

    Example
    -------
    >>> provider = FireworksProvider()
    >>> batch_id = provider.create_batch(
    ...     model="fireworks/llama-v2",
    ...     inputs=[{"prompt": "Hello"}]
    ... )
    >>> status = provider.retrieve_batch(batch_id)
    >>> results = provider.get_results(batch_id)
    """

    _BASE_URL = "https://api.fireworks.ai/v1/batches"

    def __init__(self) -> None:
        """Initialize the provider and verify authentication."""
        self.api_key = os.getenv("FIREWORKS_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "FIREWORKS_API_KEY environment variable is not set."
            )
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def create_batch(self, model: str, inputs: List[Dict[str, Any]]) -> str:
        """
        Create a new batch inference job.

        Parameters
        ----------
        model : str
            Identifier of the model to use. If an empty string is provided,
            ``fireworks/llama-v2`` is used as the default.
        inputs : list[dict]
            A list of input dictionaries, each representing a single request
            payload for the model.

        Returns
        -------
        str
            The unique identifier of the created batch job.

        Raises
        ------
        RuntimeError
            If the request fails or the response does not contain a batch ID.
        """
        if not model:
            model = "fireworks/llama-v2"

        payload = self.build_request(model, inputs)
        response = requests.post(self._BASE_URL, json=payload, headers=self.headers, timeout=30)

        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to create batch: {response.status_code} {response.text}"
            )

        data = response.json()
        batch_id = data.get("id") or data.get("batch_id")
        if not batch_id:
            raise RuntimeError("Batch creation response missing 'id' field.")
        return str(batch_id)

    def retrieve_batch(self, batch_id: str) -> Dict[str, Any]:
        """
        Retrieve the current status and metadata of a batch job.

        Parameters
        ----------
        batch_id : str
            The identifier of the batch job to query.

        Returns
        -------
        dict
            The JSON response from the Fireworks API containing status
            information such as ``status``, ``created_at``, etc.

        Raises
        ------
        RuntimeError
            If the request fails or the response cannot be parsed.
        """
        url = f"{self._BASE_URL}/{batch_id}"
        response = requests.get(url, headers=self.headers, timeout=30)

        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to retrieve batch {batch_id}: {response.status_code} {response.text}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError(f"Invalid JSON response for batch {batch_id}") from exc

    def get_results(self, batch_id: str) -> List[Dict[str, Any]]:
        """
        Fetch the results of a completed batch job.

        Parameters
        ----------
        batch_id : str
            The identifier of the batch job whose results are requested.

        Returns
        -------
        list[dict]
            A list of result dictionaries, each corresponding to an input
            entry supplied during batch creation.

        Raises
        ------
        RuntimeError
            If the batch is not yet completed or the request fails.
        """
        url = f"{self._BASE_URL}/{batch_id}/results"
        response = requests.get(url, headers=self.headers, timeout=30)

        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to get results for batch {batch_id}: {response.status_code} {response.text}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Invalid JSON response for results of batch {batch_id}") from exc

        results = data.get("results")
        if results is None:
            raise RuntimeError(f"Results field missing in response for batch {batch_id}")
        return results

    def build_request(self, model: str, inputs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Build the JSON payload required to create a batch job.

        Parameters
        ----------
        model : str
            The model identifier to be used for the batch.
        inputs : list[dict]
            A list of input dictionaries for the model.

        Returns
        -------
        dict
            The request payload conforming to Fireworks API expectations.
        """
        return {
            "model": model,
            "inputs": inputs,
        }
