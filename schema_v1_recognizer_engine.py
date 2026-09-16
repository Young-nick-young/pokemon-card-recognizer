"""Reusable SIFT/FLANN recognizer engine for Schema v1 sets.

This preserves the accepted Destined Rivals recognition behavior while
allowing new Schema v1 sets to provide only metadata and a generated library.
Destined Rivals itself remains on its established recognizer implementation.
"""

import os
import pickle
import time
from collections import defaultdict

import cv2
import numpy as np


class SchemaV1RecognizerEngine:
    GEOMETRY_CANDIDATES = 8
    MAX_SIFT_FEATURES = 500
    LOWE_RATIO = 0.78
    MIN_GOOD_MATCHES = 8

    def __init__(self, *, set_id, set_name, card_count, library_file, cards_by_number):
        self.set_id = set_id
        self.set_name = set_name
        self.card_count = card_count
        self.library_file = library_file
        self.cards_by_number = cards_by_number

        self.reference_cards = {}
        self.global_descriptors = None
        self.global_card_numbers = None
        self.global_matcher = None
        self.library_ready = False
        self.library_error = None

        self.sift = cv2.SIFT_create(
            nfeatures=self.MAX_SIFT_FEATURES,
            contrastThreshold=0.03,
            edgeThreshold=10,
            sigma=1.6,
        )

        self.index_params = dict(algorithm=1, trees=1)
        self.search_params = dict(checks=24)

    def configure_metadata(self, *, set_id, set_name, card_count, cards_by_number):
        self.set_id = set_id
        self.set_name = set_name
        self.card_count = card_count
        self.cards_by_number = cards_by_number

    def get_runtime_card_metadata(self, number):
        metadata = self.cards_by_number.get(number)
        if metadata is None:
            raise RuntimeError(
                self.set_name
                + " runtime metadata has no collector number "
                + str(number)
                + "."
            )
        return metadata

    @staticmethod
    def normalize_card_image(image):
        if image is None:
            return None
        height, width = image.shape[:2]
        max_dimension = 700
        if max(height, width) > max_dimension:
            scale = max_dimension / max(height, width)
            image = cv2.resize(
                image,
                (int(width * scale), int(height * scale)),
                interpolation=cv2.INTER_AREA,
            )
        return image

    def calculate_sift(self, image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        keypoints, descriptors = self.sift.detectAndCompute(gray, None)
        if descriptors is not None:
            descriptors = descriptors.astype(np.float32)
        return keypoints, descriptors

    def load_library(self):
        try:
            print("Loading", self.set_name, "memory-optimized card library...")
            if not os.path.exists(self.library_file):
                raise RuntimeError(self.set_name + " card_library.pkl not found.")

            with open(self.library_file, "rb") as file:
                data = pickle.load(file)

            self.reference_cards = data["cards"]
            self.global_descriptors = data["global_descriptors"]
            if self.global_descriptors.dtype != np.float32:
                self.global_descriptors = self.global_descriptors.astype(
                    np.float32,
                    copy=False,
                )
            self.global_card_numbers = data["global_card_numbers"]

            if len(self.reference_cards) != self.card_count:
                raise RuntimeError(
                    "Expected "
                    + str(self.card_count)
                    + " cards, found "
                    + str(len(self.reference_cards))
                    + "."
                )

            descriptor_mb = self.global_descriptors.nbytes / 1024 / 1024
            print("Loaded", len(self.global_descriptors), self.set_name, "features")
            print("Descriptor memory:", round(descriptor_mb, 1), "MB")
            print("Building", self.set_name, "lightweight FLANN index...")

            self.global_matcher = cv2.FlannBasedMatcher(
                self.index_params,
                self.search_params,
            )
            self.global_matcher.add([self.global_descriptors])
            self.global_matcher.train()
            self.library_ready = True
            self.library_error = None
            print(
                self.set_name,
                "library ready:",
                len(self.reference_cards),
                "cards",
            )
        except Exception as error:
            self.library_ready = False
            self.library_error = str(error)
            print(self.set_name, "library load failed:", error)

    def unload_library(self):
        self.reference_cards = {}
        self.global_descriptors = None
        self.global_card_numbers = None
        self.global_matcher = None
        self.library_ready = False
        self.library_error = None

    def rank_cards_global(self, query_descriptors):
        if query_descriptors is None or len(query_descriptors) < 2:
            return []

        matches = self.global_matcher.knnMatch(query_descriptors, k=2)
        votes = defaultdict(int)
        distances = defaultdict(float)

        for pair in matches:
            if len(pair) < 2:
                continue
            first, second = pair
            if first.distance >= self.LOWE_RATIO * second.distance:
                continue
            train_index = first.trainIdx
            if train_index < 0 or train_index >= len(self.global_card_numbers):
                continue
            number = int(self.global_card_numbers[train_index])
            votes[number] += 1
            distances[number] += first.distance

        results = []
        for number, vote_count in votes.items():
            results.append({
                "number": number,
                "votes": vote_count,
                "avg_distance": distances[number] / vote_count,
            })

        results.sort(
            key=lambda item: (item["votes"], -item["avg_distance"]),
            reverse=True,
        )
        return results

    def get_reference_descriptors(self, reference):
        return self.global_descriptors[
            reference["descriptor_start"]:reference["descriptor_end"]
        ]

    def get_card_matches(self, query_descriptors, reference_descriptors):
        if (
            query_descriptors is None
            or reference_descriptors is None
            or len(query_descriptors) < 2
            or len(reference_descriptors) < 2
        ):
            return []

        matcher = cv2.BFMatcher(cv2.NORM_L2, crossCheck=False)
        pairs = matcher.knnMatch(
            query_descriptors,
            reference_descriptors,
            k=2,
        )
        good = []
        for pair in pairs:
            if len(pair) < 2:
                continue
            first, second = pair
            if first.distance < self.LOWE_RATIO * second.distance:
                good.append(first)
        return good

    def geometric_verification(
        self,
        query_keypoints,
        reference_keypoints,
        good_matches,
    ):
        if len(good_matches) < self.MIN_GOOD_MATCHES:
            return {"inliers": 0, "inlier_ratio": 0.0}

        source_points = np.float32([
            query_keypoints[match.queryIdx].pt for match in good_matches
        ]).reshape(-1, 1, 2)
        destination_points = np.float32([
            reference_keypoints[match.trainIdx] for match in good_matches
        ]).reshape(-1, 1, 2)

        try:
            matrix, mask = cv2.findHomography(
                source_points,
                destination_points,
                cv2.RANSAC,
                5.0,
            )
            if matrix is None or mask is None:
                return {"inliers": 0, "inlier_ratio": 0.0}
            inliers = int(mask.ravel().sum())
            return {
                "inliers": inliers,
                "inlier_ratio": float(inliers / len(good_matches)),
            }
        except cv2.error:
            return {"inliers": 0, "inlier_ratio": 0.0}

    def recognize_image(self, image):
        if not self.library_ready:
            return {
                "status": "error",
                "reason": self.set_name + " library unavailable",
                "library_error": self.library_error,
                "top_matches": [],
            }

        started = time.time()
        image = self.normalize_card_image(image)

        query_started = time.time()
        query_keypoints, query_descriptors = self.calculate_sift(image)
        query_time = time.time() - query_started

        if query_descriptors is None or len(query_descriptors) < 8:
            return {
                "status": "no_match",
                "reason": "Not enough image features",
                "top_matches": [],
            }

        search_started = time.time()
        ranked = self.rank_cards_global(query_descriptors)
        global_search_time = time.time() - search_started
        if not ranked:
            return {
                "status": "no_match",
                "reason": "No feature matches",
                "top_matches": [],
            }

        geometry_started = time.time()
        final_results = []
        for candidate in ranked[:self.GEOMETRY_CANDIDATES]:
            number = candidate["number"]
            reference = self.reference_cards[number]
            reference_descriptors = self.get_reference_descriptors(reference)
            good_matches = self.get_card_matches(
                query_descriptors,
                reference_descriptors,
            )
            geometry = self.geometric_verification(
                query_keypoints,
                reference["keypoints"],
                good_matches,
            )
            inliers = geometry["inliers"]
            inlier_ratio = geometry["inlier_ratio"]
            good_count = len(good_matches)
            card_metadata = self.get_runtime_card_metadata(number)
            score = (
                inliers * 6.0
                + inlier_ratio * 220.0
                + good_count * 0.25
                + candidate["votes"] * 0.5
            )
            final_results.append({
                "number": card_metadata.number,
                "display_number": card_metadata.display_number,
                "image": card_metadata.reference_image,
                "global_votes": candidate["votes"],
                "good_matches": good_count,
                "inliers": inliers,
                "inlier_ratio": round(inlier_ratio, 4),
                "score": round(score, 3),
            })

        geometry_time = time.time() - geometry_started
        final_results.sort(key=lambda item: item["score"], reverse=True)
        if not final_results:
            return {
                "status": "no_match",
                "reason": "No verified candidates",
                "top_matches": [],
            }

        best = final_results[0]
        second = final_results[1] if len(final_results) > 1 else None
        score_gap = best["score"] - second["score"] if second else best["score"]

        confident = False
        if (
            best["inliers"] >= 16
            and best["inlier_ratio"] >= 0.42
            and score_gap >= 18
        ):
            confident = True
        if best["inliers"] >= 28 and best["inlier_ratio"] >= 0.50:
            confident = True

        total_time = time.time() - started
        return {
            "status": "matched",
            "set": self.set_name,
            "set_id": self.set_id,
            "best_match": best,
            "confident": confident,
            "score_gap": round(score_gap, 3),
            "top_matches": final_results[:5],
            "timing": {
                "query_sift": round(query_time, 3),
                "global_search": round(global_search_time, 3),
                "geometry": round(geometry_time, 3),
                "total": round(total_time, 3),
            },
        }

    def get_status(self):
        return {
            "set": self.set_name,
            "set_id": self.set_id,
            "library_ready": self.library_ready,
            "cards_prepared": len(self.reference_cards),
            "cards_expected": self.card_count,
            "global_features": (
                len(self.global_descriptors)
                if self.global_descriptors is not None
                else 0
            ),
            "library_error": self.library_error,
        }
