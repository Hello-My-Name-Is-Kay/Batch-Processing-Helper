import os
from typing import Any, Dict, List

import requests

from .base import BatchProvider


class AnyscaleProvider(BatchProvider):
    """
    Anyscale (Ray) batch provider implementation.

    This provider interacts with the Anyscale API to submit batch inference
    jobs to Ray Serve endpoints. Authentication is performed via the
    ``ANYSCALE_API_KEY`` environment variable.

    The provider assumes a generic batch endpoint at
    ``https://api.anyscale.com/v1/batches``.  The ``model`` argument should be
    the name of a Ray Serve deployment that can handle the supplied inputs.
    """

    _BASE_URL = "https://api.anyscale.com/v1/batches"

    def __init__(self) -> None:
        """Create a new :class:`AnyscaleProvider` instance.

        Raises:
            RuntimeError: If the ``ANYSCALE_API_KEY`` environment variable is not set.
        """
        self.api_key = os.getenv("ANYSCALE_API_KEY")
        if not self.api_key:
            raise RuntimeError("ANYSCALE_API_KEY environment variable is required for AnyscaleProvider")

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def create_batch(self, model: str, inputs: List[Dict[str, Any]]) -> str:
        """
        Submit a new batch job to Anyscale.

        Args:
            model: The name of the Ray Serve deployment to invoke.
            inputs: A list of dictionaries, each representing a single request payload.

        Returns:
            The batch identifier returned by the Anyscale API.

        Raises:
            RuntimeError: If the request fails or the response does not contain a batch ID.
        """
        payload = self.build_request(model, inputs)
        response = requests.post(self._BASE_URL, headers=self.headers, json=payload, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(f"Failed to create batch: {response.status_code} {response.text}")

        data = response.json()
        batch_id = data.get("batch_id") or data.get("id")
        if not batch_id:
            raise RuntimeError("Anyscale response missing batch identifier")
        return str(batch_id)

    def retrieve_batch(self, batch_id: str) -> Dict[str, Any]:
        """
        Retrieve the status and metadata of an existing batch.

        Args:
            batch_id: Identifier of the batch to retrieve.

        Returns:
            A dictionary containing batch details as returned by the Anyscale API.

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
        Fetch the results of a completed batch job.

        Args:
            batch_id: Identifier of the batch whose results are requested.

        Returns:
            A list of result dictionaries, one per input item.

        Raises:
            RuntimeError: If the request fails or results are unavailable.
        """
        url = f"{self._BASE_URL}/{batch_id}/results"
        response = requests.get(url, headers=self.headers, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(f"Failed to get results for batch {batch_id}: {response.status_code} {response.text}")

        data = response.json()
        results = data.get("results")
        if results is None:
            raise RuntimeError(f"Anyscale response missing results for batch {batch_id}")
        return results

    def build_request(self, model: str, inputs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Construct the JSON payload required by the Anyscale batch endpoint.

        Args:
            model: The Ray Serve deployment name to invoke.
            inputs: A list of input dictionaries for the batch.

        Returns:
            A dictionary representing the request body.
        """
        return {
            "model": model,
            "inputs": inputs,
        }
