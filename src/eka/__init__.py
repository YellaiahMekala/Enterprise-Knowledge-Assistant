# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""eka: chat with your documents, with answers that cite document, page and passage."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("eka")
except PackageNotFoundError:  # source tree that was never installed
    __version__ = "0.0.0"
