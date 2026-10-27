import os
from typing import Any, Dict, List

import requests

from .base import BatchProvider


class LambdaProvider(BatchProvider):
    """
    Batch provider for Lambda Labs GPU cloud.

    This provider interacts with the Lambda Labs batch endpoint to submit
    inference jobs for custom models hosted on the platform.

    Authentication is performed via the ``LAMBDA_API_KEY`` environment variable.
    """

    _BASE_URL = "https://api.lambda.com/v1/batches"

    def __init__(self) -> None:
        """Initialize the provider and verify that the API key is available."""
        self.api_key = os.getenv("LAMBDA_API_KEY")
        if not self.api_key:
            raise RuntimeError("Environment variable LAMBDA_API_KEY is required for LambdaProvider.")

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def create_batch(self, model: str, inputs: List[Dict[str, Any]]) -> str:
        """
        Submit a new batch job to Lambda Labs.

        Args:
            model: Identifier of the model deployed on Lambda Labs.
            inputs: A list of dictionaries, each representing a single inference request
                payload as expected by the model.

        Returns:
            The batch identifier returned by the Lambda API.

        Raises:
            RuntimeError: If the request fails or the response does not contain a batch ID.
        """
        payload = self.build_request(model, inputs)
        response = requests.post(self._BASE_URL, json=payload, headers=self.headers, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(f"Failed to create batch: {response.status_code} {response.text}")

        data = response.json()
        batch_id = data.get("id")
        if not batch_id:
            raise RuntimeError("Batch creation response missing 'id' field.")
        return batch_id

    def retrieve_batch(self, batch_id: str) -> Dict[str, Any]:
        """
        Retrieve the status and metadata of an existing batch.

        Args:
            batch_id: The identifier of the batch to retrieve.

        Returns:
            A dictionary containing batch details as returned by the Lambda API.

        Raises:
            RuntimeError: If the request fails.
        """
        url = f"{self._BASE_URL}/{batch_id}"
        response = requests.get(url, headers=self.headers, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(f"Failed to retrieve batch {batch_id}: {response.status_code} {response.text}")
        return response.json()

    def get_results(self, batch_id: str) -> List[Dict[str, Any]]:
        """
        Fetch the results of a completed batch.

        Args:
            batch_id: The identifier of the batch whose results are requested.

        Returns:
            A list of result dictionaries, one per input item.

        Raises:
            RuntimeError: If the request fails or the batch is not yet completed.
        """
        url = f"{self._BASE_URL}/{batch_id}/results"
        response = requests.get(url, headers=self.headers, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(f"Failed to get results for batch {batch_id}: {response.status_code} {response.text}")

        data = response.json()
        results = data.get("results")
        if results is None:
            raise RuntimeError("Results response missing 'results' field.")
        return results

    def build_request(self, model: str, inputs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Construct the request payload for creating a batch.

        Args:
            model: The model identifier on Lambda Labs.
            inputs: A list of input dictionaries for the model.

        Returns:
            A dictionary ready to be JSON‑encoded and sent to the Lambda batch endpoint.
        """
        return {
            "model": model,
            "inputs": inputs,
        }
