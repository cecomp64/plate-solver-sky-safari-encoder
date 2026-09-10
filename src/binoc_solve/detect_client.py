"""gRPC client for cedar-detect-server, following the shared-memory pattern
from upstream's own tetra3/cedar_detect_client.py example (the shmem path
is much faster than sending the image bytes over the gRPC channel, and
only works because the server runs on the same machine - true here since
cedar-detect-server is a local systemd service).
"""
from __future__ import annotations

import logging
from multiprocessing import shared_memory

import grpc
import numpy as np

logger = logging.getLogger(__name__)

_SHMEM_NAME = "/binoc_solve_image"


class DetectClient:
    def __init__(self, address: str, sigma: float) -> None:
        # cedar-solve's `tetra3` package vendors the generated gRPC stubs
        # (tetra3/cedar_detect_pb2*.py) alongside the Tetra3 solver itself -
        # see SETUP.md. Imported here (not at module level) so this module,
        # and anything that imports it (including main.py), stays importable
        # without cedar-solve installed - see scripts/simulate_skysafari.py,
        # which needs exactly that to run without the full solver stack.
        # Falls back to a bare import in case the stubs are only on the path
        # as standalone modules (e.g. generated directly from cedar-detect's
        # own proto per its README, rather than via cedar-solve's copy).
        try:
            from tetra3 import cedar_detect_pb2, cedar_detect_pb2_grpc  # noqa: PLC0415
        except ImportError:  # pragma: no cover - depends on target install layout
            import cedar_detect_pb2  # noqa: PLC0415
            import cedar_detect_pb2_grpc  # noqa: PLC0415

        self._cedar_detect_pb2 = cedar_detect_pb2
        self._cedar_detect_pb2_grpc = cedar_detect_pb2_grpc
        self._sigma = sigma
        self._channel = grpc.insecure_channel(address)
        self._stub = cedar_detect_pb2_grpc.CedarDetectStub(self._channel)

    def extract_centroids(self, image: np.ndarray) -> list[tuple[float, float]]:
        """Returns (y, x) centroids, brightest first - the order and shape
        Tetra3.solve_from_centroids() expects."""
        height, width = image.shape[:2]
        shmem = shared_memory.SharedMemory(_SHMEM_NAME, create=True, size=height * width)
        try:
            shared_image = np.ndarray(image.shape, dtype=image.dtype, buffer=shmem.buf)
            shared_image[:] = image[:]

            request = self._cedar_detect_pb2.CentroidsRequest(
                input_image=self._cedar_detect_pb2.Image(
                    width=width, height=height, shmem_name=shmem.name
                ),
                sigma=self._sigma,
                use_binned_for_star_candidates=True,
            )
            result = self._stub.ExtractCentroids(request)
        finally:
            shmem.close()
            shmem.unlink()

        centroids = [
            (sc.centroid_position.y, sc.centroid_position.x) for sc in result.star_candidates
        ]
        logger.debug(
            "cedar-detect found %d centroids (noise=%.2f, peak=%d)",
            len(centroids), result.noise_estimate, result.peak_star_pixel,
        )
        return centroids
