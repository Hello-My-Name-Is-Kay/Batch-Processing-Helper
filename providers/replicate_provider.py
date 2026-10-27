import os
import uuid
from typing import Any, Dict, List

import requests

from .base import BatchProvider


class ReplicateProvider(BatchProvider):
    """
    Replicate.com batch provider.

    This provider uses the Replicate API to create and manage batch predictions.
    Authentication is performed via the ``REPLICATE_API_KEY`` environment variable.
    """

    _BASE_URL = "https://api.replicate.com/v1/predictions"

    def __init__(self) -> None:
        """
        Initialise the provider and verify that the required API key is present.

        Raises:
            RuntimeError: If ``REPLICATE_API_KEY`` is not set in the environment.
        """
        self.api_key = os.getenv("REPLICATE_API_KEY")
        if not self.api_key:
            raise RuntimeError("Environment variable REPLICATE_API_KEY is required for ReplicateProvider.")
        self.headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json",
        }

    def create_batch(self, model: str, inputs: List[Dict[str, Any]]) -> str:
        """
        Create a batch prediction on Replicate.

        Args:
            model: The Replicate model identifier (e.g., ``"owner/model:version"``).
            inputs: A list of input dictionaries matching the model's schema.

        Returns:
            A string batch identifier that can be used with ``retrieve_batch`` and ``get_results``.

        Raises:
            requests.HTTPError: If the API request fails.
        """
        # Replicate does not have a native batch endpoint; we simulate it by
        # creating a unique batch ID and storing the individual prediction IDs.
        batch_id = str(uuid.uuid4())
        prediction_ids = []

        for input_item in inputs:
            payload = self.build_request(model, [input_item])
            response = requests.post(self._BASE_URL, json=payload, headers=self.headers, timeout=30)
            response.raise_for_status()
            prediction_ids.append(response.json()["id"])

        # Store the mapping locally; in a real implementation this would be persisted.
        # For the purpose of this helper we attach it to the instance.
        if not hasattr(self, "_batch_store"):
            self._batch_store: Dict[str, List[str]] = {}
        self._batch_store[batch_id] = prediction_ids
        return batch_id

    def retrieve_batch(self, batch_id: str) -> Dict[str, Any]:
        """
        Retrieve the status of all predictions belonging to a batch.

        Args:
            batch_id: The identifier returned by ``create_batch``.

        Returns:
            A dictionary containing the batch status and a list of individual prediction
            statuses.

        Raises:
            KeyError: If the batch_id is unknown.
            requests.HTTPError: If any individual prediction request fails.
        """
        if not hasattr(self, "_batch_store") or batch_id not in self._batch_store:
            raise KeyError(f"Batch ID {batch_id} not found.")

        prediction_ids = self._batch_store[batch_id]
        statuses = []
        for pid in prediction_ids:
            resp = requests.get(f"{self._BASE_URL}/{pid}", headers=self.headers, timeout=30)
            resp.raise_for_status()
            statuses.append(resp.json())

        return {"batch_id": batch_id, "predictions": statuses}

    def get_results(self, batch_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve the final results of a completed batch.

        Args:
            batch_id: The identifier returned by ``create_batch``.

        Returns:
            A list of result dictionaries extracted from each prediction.

        Raises:
            KeyError: If the batch_id is unknown.
            RuntimeError: If any prediction has not yet completed.
        """
        batch_info = self.retrieve_batch(batch_id)
        results: List[Dict[str, Any]] = []

        for pred in batch_info["predictions"]:
            if pred.get("status") != "succeeded":
                raise RuntimeError(f"Prediction {pred.get('id')} not completed: {pred.get('status')}")
            # Replicate returns the output under the "output" key.
            results.append({"id": pred.get("id"), "output": pred.get("output")})

        return results

    def build_request(self, model: str, inputs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Build the JSON payload for a Replicate prediction request.

        Args:
            model: The Replicate model identifier.
            inputs: A list containing a single input dictionary (Replicate expects one at a time).

        Returns:
            A dictionary suitable for ``requests.post`` to the Replicate predictions endpoint.

        Raises:
            ValueError: If ``inputs`` does not contain exactly one element.
        """
        if len(inputs) != 1:
            raise ValueError("ReplicateProvider expects a single input per request; batch handling is performed by create_batch.")
        return {
            "version": model,
            "input": inputs[0],
        }
