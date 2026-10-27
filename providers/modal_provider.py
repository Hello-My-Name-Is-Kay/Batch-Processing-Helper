import os
import json
from typing import Any, Dict, List

import requests

from .base import BatchProvider


class ModalProvider(BatchProvider):
    """
    Batch provider for Modal cloud functions.

    This provider creates and manages batch jobs that invoke a user‑deployed
    Modal function. The function name (or identifier) is supplied as the
    ``model`` argument to the public methods.

    Authentication is performed via two environment variables:
    ``MODAL_TOKEN_ID`` and ``MODAL_TOKEN_SECRET``. Both must be present,
    otherwise a :class:`RuntimeError` is raised.
    """

    _BASE_URL = "https://api.modal.com/v1/batches"

    def __init__(self) -> None:
        """
        Initialise the provider and verify required authentication variables.

        Raises:
            RuntimeError: If ``MODAL_TOKEN_ID`` or ``MODAL_TOKEN_SECRET`` is not set.
        """
        token_id = os.getenv("MODAL_TOKEN_ID")
        token_secret = os.getenv("MODAL_TOKEN_SECRET")
        if not token_id or not token_secret:
            raise RuntimeError(
                "Modal authentication requires both MODAL_TOKEN_ID and MODAL_TOKEN_SECRET environment variables."
            )
        self._auth_headers = {
            "Authorization": f"Bearer {token_id}:{token_secret}",
            "Content-Type": "application/json",
        }

    def create_batch(self, model: str, inputs: List[Dict[str, Any]]) -> str:
        """
        Submit a new batch job to Modal.

        Args:
            model: The name or identifier of the deployed Modal function to invoke.
            inputs: A list of dictionaries, each representing the payload for a single
                function invocation.

        Returns:
            The batch identifier returned by Modal.

        Raises:
            RuntimeError: If the request fails or the response does not contain a batch ID.
        """
        payload = self.build_request(model, inputs)
        response = requests.post(
            self._BASE_URL, headers=self._auth_headers, data=json.dumps(payload)
        )
        # Modal may return 200 or 202 on success; accept both.
        if response.status_code not in (200, 202):
            raise RuntimeError(
                f"Failed to create Modal batch: {response.status_code} {response.text}"
            )
        data = response.json()
        batch_id = data.get("batch_id")
        if not batch_id:
            raise RuntimeError("Modal response missing 'batch_id'.")
        return batch_id

    def retrieve_batch(self, batch_id: str) -> Dict[str, Any]:
        """
        Retrieve the status and metadata of an existing Modal batch.

        Args:
            batch_id: The identifier of the batch to retrieve.

        Returns:
            A dictionary containing batch details as returned by Modal.

        Raises:
            RuntimeError: If the request fails.
        """
        url = f"{self._BASE_URL}/{batch_id}"
        response = requests.get(url, headers=self._auth_headers)
        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to retrieve Modal batch {batch_id}: {response.status_code} {response.text}"
            )
        return response.json()

    def get_results(self, batch_id: str) -> List[Dict[str, Any]]:
        """
        Fetch the results of a completed Modal batch.

        Args:
            batch_id: The identifier of the batch whose results are requested.

        Returns:
            A list of result dictionaries, one per input item.

        Raises:
            RuntimeError: If the batch is not completed or the request fails.
        """
        url = f"{self._BASE_URL}/{batch_id}/results"
        response = requests.get(url, headers=self._auth_headers)
        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to get results for Modal batch {batch_id}: {response.status_code} {response.text}"
            )
        data = response.json()
        results = data.get("results")
        if results is None:
            raise RuntimeError("Modal response missing 'results' field.")
        return results

    def build_request(self, model: str, inputs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Construct the request payload for creating a Modal batch.

        The payload follows Modal's batch API specification, where each input
        is sent as a separate task invoking the specified function.

        Args:
            model: The name/identifier of the Modal function to call.
            inputs: A list of dictionaries representing the arguments for each
                function invocation.

        Returns:
            A dictionary ready to be JSON‑encoded and sent to the Modal batch endpoint.
        """
        tasks = [{"function": model, "payload": inp} for inp in inputs]
        return {"tasks": tasks}
