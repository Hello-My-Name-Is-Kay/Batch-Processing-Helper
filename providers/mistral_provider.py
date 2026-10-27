import os
import json
from typing import Any, Dict, List

import requests

from .base import BatchProvider


class MistralProvider(BatchProvider):
    """
    Batch provider for Mistral AI.

    This provider implements the :class:`BatchProvider` interface for the
    Mistral AI batch API.  All network interactions are performed with the
    ``requests`` library, but the implementation only builds the request
    payloads and parses the expected JSON responses – real HTTP calls are
    expected to be mocked in unit tests.

    Environment Variables
    ---------------------
    - ``MISTRAL_API_KEY`` – API key used for authentication.  A
      :class:`RuntimeError` is raised if the variable is not set.
    """

    _BASE_URL = "https://api.mistral.ai/v1/batches"

    def __init__(self) -> None:
        """Create a new :class:`MistralProvider` instance."""
        api_key = os.getenv("MISTRAL_API_KEY")
        if not api_key:
            raise RuntimeError("MISTRAL_API_KEY environment variable is not set")
        self._api_key = api_key
        self._headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def create_batch(self, model: str, inputs: List[Dict[str, Any]]) -> str:
        """
        Submit a batch job to Mistral AI.

        Parameters
        ----------
        model: str
            The model identifier to use.  If an empty string is supplied,
            ``mistral-large`` is used as the default.
        inputs: list[dict]
            A list of input dictionaries, each representing a single request
            payload for the model.

        Returns
        -------
        str
            The identifier of the created batch job.

        Raises
        ------
        RuntimeError
            If the request fails or the response does not contain a batch ID.
        """
        if not model:
            model = "mistral-large"

        payload = self.build_request(model, inputs)
        response = requests.post(self._BASE_URL, headers=self._headers, json=payload)

        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to create Mistral batch: {response.status_code} {response.text}"
            )

        data = response.json()
        batch_id = data.get("id")
        if not batch_id:
            raise RuntimeError("Mistral batch creation response missing 'id'")
        return batch_id

    def retrieve_batch(self, batch_id: str) -> Dict[str, Any]:
        """
        Retrieve the status and metadata of a previously created batch.

        Parameters
        ----------
        batch_id: str
            The identifier of the batch job to retrieve.

        Returns
        -------
        dict
            The JSON response from the Mistral API containing batch details.

        Raises
        ------
        RuntimeError
            If the request fails or the response cannot be parsed.
        """
        url = f"{self._BASE_URL}/{batch_id}"
        response = requests.get(url, headers=self._headers)

        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to retrieve Mistral batch {batch_id}: {response.status_code} {response.text}"
            )

        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON response for batch {batch_id}") from exc

    def get_results(self, batch_id: str) -> List[Dict[str, Any]]:
        """
        Fetch the results of a completed batch job.

        Parameters
        ----------
        batch_id: str
            The identifier of the batch job whose results are requested.

        Returns
        -------
        list[dict]
            A list of result objects as returned by the Mistral API.

        Raises
        ------
        RuntimeError
            If the request fails or the response format is unexpected.
        """
        url = f"{self._BASE_URL}/{batch_id}/results"
        response = requests.get(url, headers=self._headers)

        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to get results for Mistral batch {batch_id}: {response.status_code} {response.text}"
            )

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON when fetching results for batch {batch_id}") from exc

        results = data.get("results")
        if results is None:
            raise RuntimeError(f"Results field missing in response for batch {batch_id}")
        return results

    def build_request(self, model: str, inputs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Construct the JSON payload required to create a Mistral batch.

        Parameters
        ----------
        model: str
            The model identifier to use for the batch.
        inputs: list[dict]
            A list of input dictionaries, each containing the fields required by
            the Mistral inference endpoint (e.g., ``prompt``).

        Returns
        -------
        dict
            The request body that should be sent to the Mistral batch endpoint.
        """
        return {
            "model": model,
            "inputs": inputs,
        }
