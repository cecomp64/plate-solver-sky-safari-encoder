"""gRPC client for cedar-detect-server, following the shared-memory pattern
from upstream's own tetra3/cedar_detect_client.py example (the shmem path
is much faster than sending the image bytes over the gRPC channel, and
only works because the server runs on the same machine - true here since
cedar-detect-server is a local systemd service).
"""
from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from multiprocessing import shared_memory

import grpc
import numpy as np

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DetectionResult:
    """(y, x) centroids plus the two cedar-detect stats auto_exposure.py
    needs to judge exposure health: peak_star_pixel (0-255, saturation)
    and noise_estimate (background noise floor)."""

    centroids: list[tuple[float, float]]
    peak_star_pixel: int
    noise_estimate: float


class DetectClient:
    def __init__(self, address: str, sigma: float, binning: int) -> None:
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
        self._binning = binning
        self._channel = grpc.insecure_channel(address)
        self._stub = cedar_detect_pb2_grpc.CedarDetectStub(self._channel)

    def extract_centroids(self, image: np.ndarray) -> DetectionResult:
        """Returns (y, x) centroids, brightest first - the order and shape
        Tetra3.solve_from_centroids() expects - plus the exposure-health
        stats in DetectionResult."""
        height, width = image.shape[:2]
        # Unique per call, not a fixed name: cedar-detect-server may field
        # requests from more than one process at once (e.g. the live
        # service plus a one-off script like solve_image.py, or two
        # DetectClient instances in the same process as SYNTHETIC mode
        # adds) - a shared fixed name let one caller's create/unlink race
        # another's, corrupting whichever request lost the race with a
        # torn or already-freed buffer. Confirmed by hand: centroids
        # against test_images/synthetic_orion.png were wrong/near-zero
        # while the live service was concurrently polling the real
        # camera through the same fixed name; a fresh, uncontended name
        # fixed it immediately.
        shmem_name = f"/binoc_solve_image_{os.getpid()}_{uuid.uuid4().hex}"
        shmem = shared_memory.SharedMemory(shmem_name, create=True, size=height * width)
        try:
            shared_image = np.ndarray(image.shape, dtype=image.dtype, buffer=shmem.buf)
            shared_image[:] = image[:]

            request = self._cedar_detect_pb2.CentroidsRequest(
                input_image=self._cedar_detect_pb2.Image(
                    width=width, height=height, shmem_name=shmem.name,
                    # Without this, cedar-detect-server caches the fd from
                    # its *first-ever* request and keeps mmap'ing that same
                    # stale shared-memory object forever, silently ignoring
                    # every later shmem_name - confirmed by hand: a
                    # long-running server kept re-analyzing its first
                    # captured frame no matter what image was actually
                    # sent afterward, while a freshly restarted server
                    # (or one told to reopen) read the real, current image.
                    reopen_shmem=True,
                ),
                sigma=self._sigma,
                use_binned_for_star_candidates=True,
                binning=self._binning,
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
        return DetectionResult(
            centroids=centroids,
            peak_star_pixel=result.peak_star_pixel,
            noise_estimate=result.noise_estimate,
        )
