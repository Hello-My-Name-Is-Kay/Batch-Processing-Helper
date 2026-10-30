import os
from typing import Any, Dict, List

import requests

from .base import BatchProvider


class BasetenProvider(BatchProvider):
    """
    Baseten ML platform batch provider.

    This provider interacts with the Baseten batch API to submit inference
    jobs, retrieve batch status, and fetch results. Authentication is performed
    using the ``BASETEN_API_KEY`` environment variable.
    """

    _BASE_URL = "https://api.baseten.co/v1/batches"

    def __init__(self) -> None:
        """
        Initialise the provider and verify that the required API key is present.

        Raises:
            RuntimeError: If ``BASETEN_API_KEY`` is not set in the environment.
        """
        self.api_key = os.getenv("BASETEN_API_KEY")
        if not self.api_key:
            raise RuntimeError("Missing required environment variable: BASETEN_API_KEY")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def create_batch(self, model: str, inputs: List[Dict[str, Any]]) -> str:
        """
        Submit a new batch job to Baseten.

        Args:
            model: The identifier of the Baseten model to invoke.
            inputs: A list of input dictionaries, each representing a single request
                payload for the model.

        Returns:
            The batch identifier returned by Baseten.

        Raises:
            RuntimeError: If the HTTP request fails or the response does not contain a batch ID.
        """
        payload = self.build_request(model, inputs)
        response = requests.post(self._BASE_URL, headers=self.headers, json=payload)
        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to create batch: {response.status_code} {response.text}"
            )
        data = response.json()
        batch_id = data.get("batch_id") or data.get("id")
        if not batch_id:
            raise RuntimeError("Batch creation response missing 'batch_id'")
        return str(batch_id)

    def retrieve_batch(self, batch_id: str) -> Dict[str, Any]:
        """
        Retrieve the status and metadata of an existing batch.

        Args:
            batch_id: The identifier of the batch to retrieve.

        Returns:
            A dictionary containing batch details as returned by Baseten.

        Raises:
            RuntimeError: If the HTTP request fails.
        """
        url = f"{self._BASE_URL}/{batch_id}"
        response = requests.get(url, headers=self.headers)
        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to retrieve batch {batch_id}: {response.status_code} {response.text}"
            )
        return response.json()

    def get_results(self, batch_id: str) -> List[Dict[str, Any]]:
        """
        Fetch the results of a completed batch.

        Args:
            batch_id: The identifier of the batch whose results are requested.

        Returns:
            A list of result dictionaries, one per input item.

        Raises:
            RuntimeError: If the batch is not yet completed or the request fails.
        """
        batch_info = self.retrieve_batch(batch_id)
        status = batch_info.get("status")
        if status != "completed":
            raise RuntimeError(f"Batch {batch_id} is not completed (status: {status})")
        results_url = batch_info.get("results_url")
        if not results_url:
            raise RuntimeError(f"Batch {batch_id} missing 'results_url' in response")
        response = requests.get(results_url, headers=self.headers)
        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to fetch results for batch {batch_id}: {response.status_code} {response.text}"
            )
        return response.json().get("results", [])

    def build_request(self, model: str, inputs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Construct the JSON payload required by Baseten to start a batch job.

        Args:
            model: The Baseten model identifier.
            inputs: A list of input dictionaries for the model.

        Returns:
            A dictionary representing the request body.
        """
        return {
            "model": model,
            "inputs": inputs,
        }
