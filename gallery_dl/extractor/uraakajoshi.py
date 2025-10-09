# -*- coding: utf-8 -*-

# Copyright 2016-2025 Mike Fährmann
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.

"""Extractors for https://www.uraaka-joshi.com/"""

from .common import Extractor, Message
from .. import text
import datetime


BASE_PATTERN = r"(?:https?://)?(?:www\.)?uraaka-joshi\.com"
USER_PATTERN = rf"{BASE_PATTERN}/user/([^/?#]+)"
TAG_PATTERN = rf"{BASE_PATTERN}/hashtag/([^/?#]+)(?:/page/(\d+))?"


class UraakajoshiExtractor(Extractor):
	"""Base class for uraaka-joshi extractors"""

	category = "uraakajoshi"
	directory_fmt = ("{category}", "{user[screen_name]}")
	filename_fmt = "{tweet_id}_{num}.{extension}"
	archive_fmt = "{tweet_id}_{num}"
	root = "https://www.uraaka-joshi.com"
	# request_interval = (0.5, 1.5)

	def __init__(self, match):
		Extractor.__init__(self, match)
		self.user = match[1] if match else None
		self._user_data = None

	def items(self):
		self.api = UraakajoshiAPI(self)

		for tweet_data in self.tweets():
			tweet = self._transform_tweet(tweet_data)
			files = self._extract_files(tweet_data)

			if not files:
				continue

			yield Message.Directory, tweet

			for num, file_data in enumerate(files, 1):
				url = file_data.pop("_url")  # Extract URL and remove from metadata
				file_data.update(tweet)
				file_data["num"] = num
				yield Message.Url, url, file_data

	def _extract_files(self, data):
		"""Extract media files from tweet data"""
		files = []

		if "media" in data and data["media"]:
			user_data = data["user"]
			tweet_data = data["tweet"]

			# Extract date components from tweet created timestamp
			# Format: YYYY-MM-DD HH:MM:SS -> YYYYMM and YYYYMMDDHHMMSS
			created = tweet_data["created"]
			try:
				# Parse date: "2023-07-13 06:03:38"
				dt = datetime.datetime.strptime(created, "%Y-%m-%d %H:%M:%S")
				date_folder = dt.strftime("%Y%m")  # 202307
				timestamp_folder = dt.strftime("%Y%m%d%H%M%S")  # 20230713060338
			except ValueError:
				# Fallback if date parsing fails
				date_folder = "unknown"
				timestamp_folder = "unknown"

			# Get username and first character for URL path
			username = user_data["screen_name"]
			first_char = username[0]

			for media in data["media"]:
				# Prioritize video over photo - if video_file_name exists and is not empty, use video
				if media.get("video_file_name"):
					# Video file (prioritized over photo)
					url = f"{self.root}/media/{first_char}/{username}/{date_folder}/{timestamp_folder}/{media['video_file_name']}"
					files.append(
						{
							"_url": url,
							"media_id": text.parse_int(media["id"]),
							"extension": media["video_file_name"].split(".")[-1],
							"type": "video",
						}
					)
				elif media.get("photo_file_name"):
					# Photo file (only if no video)
					url = f"{self.root}/media/{first_char}/{username}/{date_folder}/{timestamp_folder}/{media['photo_file_name']}"
					files.append(
						{
							"_url": url,
							"media_id": text.parse_int(media["id"]),
							"width": media.get("photo_width", 0),
							"height": media.get("photo_height", 0),
							"extension": media["photo_file_name"].split(".")[-1],
							"type": "photo",
						}
					)

		return files

	def _transform_tweet(self, data):
		"""Transform API data into standardized tweet format"""
		user_data = data["user"]
		tweet_data = data["tweet"]

		# Transform user data
		user = {
			"id": text.parse_int(user_data["id"]),
			"screen_name": user_data["screen_name"],
			"name": user_data["name"],
			"description": user_data["description"],
			"location": user_data["location"],
			"followers_count": user_data["followers_count"],
			"created": user_data["created"],
			"public_date": user_data["public_date"],
			"followers_ranking": user_data.get("followers_ranking", 0),
			"protected": user_data.get("protected", False),
			"suspended": user_data.get("suspended", False),
			"hashtags": user_data.get("hashtags", []),
		}

		# Transform tweet data
		tweet_id = text.parse_int(tweet_data["id"])

		return {
			"tweet_id": tweet_id,
			"id": tweet_id,  # For compatibility
			"content": text.unescape(tweet_data["text"]),
			"date": text.parse_datetime(tweet_data["created"], "%Y-%m-%d %H:%M:%S"),
			"created": tweet_data["created"],
			"type": tweet_data.get("type", ""),
			"access_ranking": tweet_data.get("access_ranking", ""),
			"user": user,
			"screen_name": data["screen_name"],
		}

	def tweets(self):
		"""Generate tweet data - to be overridden by subclasses"""
		return []

	def metadata(self):
		"""Return metadata for the extraction"""
		return {}


class UraakajoshiUserExtractor(UraakajoshiExtractor):
	"""Extractor for a Uraaka-joshi user timeline"""

	subcategory = "user"
	pattern = USER_PATTERN + r"/?(?:$|\?|#)"
	example = "https://www.uraaka-joshi.com/user/USERNAME"

	def tweets(self):
		"""Fetch tweets from user timeline"""
		return self.api.user_timeline(self.user)

	def metadata(self):
		"""Return user metadata"""
		if self._user_data is None:
			# Get user data from first tweet if available
			for tweet_data in self.api.user_timeline(self.user, max_pages=1):
				self._user_data = self._transform_tweet(tweet_data)["user"]
				break

		return {"user": self._user_data} if self._user_data else {}


class UraakajoshiTagExtractor(UraakajoshiExtractor):
	"""Extractor for Uraaka-joshi hashtag feeds"""

	subcategory = "tag"
	pattern = TAG_PATTERN + r"/?(?:$|\?|#)"
	example = "https://www.uraaka-joshi.com/hashtag/HASHTAG/page/2000"

	def __init__(self, match):
		UraakajoshiExtractor.__init__(self, match)
		self.tag = match[1] if match else None
		self.page_start = text.parse_int(match[2]) if match and match[2] else 1

	def items(self):
		"""Generate users from hashtag feed"""
		self.api = UraakajoshiAPI(self)

		# Collect unique usernames from hashtag feed
		seen_users = set()

		for tweet_data in self.api.hashtag_timeline(self.tag, page_start=self.page_start):
			user_data = tweet_data.get("user", {})
			username = user_data.get("screen_name")

			if username and username not in seen_users:
				seen_users.add(username)

				# Yield user URL for the user extractor to process
				user_url = f"{self.root}/user/{username}"
				yield Message.Queue, user_url, {"_extractor": UraakajoshiUserExtractor}

	def metadata(self):
		"""Return hashtag metadata"""
		return {"tag": self.tag}


class UraakajoshiAPI:
	"""API handler for Uraaka-joshi"""

	def __init__(self, extractor):
		self.extractor = extractor
		self.root = extractor.root

	def user_timeline(self, username, max_pages=None):
		"""Fetch user timeline with pagination"""
		page_no = 1

		while True:
			if max_pages and page_no > max_pages:
				break

			current_time = datetime.datetime.now().strftime("%Y%m%d%H%M")
			one_char = username[0]

			# Calculate page_name based on page_no
			# page_name increases by 1000 every 1000 pages
			# (page_no = 999, page_name = 000999), (page_no = 1000, page_name = 001999)
			page_name_number = (page_no // 1000) * 1000 + 999
			page_name = f"{page_name_number:06d}"

			params = {
				"json_item": "user",
				"json_val": username,
				"one_char": one_char,
				"page_name": page_name,
				"page_no": str(page_no),
				"time": current_time,
			}

			url = f"{self.root}/json/timeline/"
			response = self.extractor.request(url, params=params)

			try:
				data = response.json()
			except Exception as exc:
				self.extractor.log.debug("Failed to parse JSON response: %s", exc)
				break

			if not data.get("data"):
				self.extractor.log.debug("No data found in response")
				break

			# Yield each tweet in the current page
			for item in data["data"]:
				yield item

			# Check if there's a next page
			current_page = data.get("current", 1)
			next_page = data.get("next")

			if not next_page or next_page <= current_page:
				break

			page_no = next_page

	def hashtag_timeline(self, hashtag, max_pages=None, page_start=1):
		"""Fetch hashtag timeline with pagination"""
		page_no = page_start

		while True:
			if max_pages and page_no > (page_start + max_pages - 1):
				break

			current_time = datetime.datetime.now().strftime("%Y%m%d%H%M")

			# Calculate page_name based on page_no
			# page_name increases by 1000 every 1000 pages
			# (page_no = 999, page_name = 000999), (page_no = 1000, page_name = 001999)
			page_name_number = (page_no // 1000) * 1000 + 999
			page_name = f"{page_name_number:06d}"

			params = {
				"json_item": "hashtag",
				"json_val": hashtag,
				"page_name": page_name,
				"page_no": str(page_no),
				"time": current_time,
			}

			url = f"{self.root}/json/timeline/"
			response = self.extractor.request(url, params=params)

			try:
				data = response.json()
			except Exception as exc:
				self.extractor.log.debug("Failed to parse JSON response: %s", exc)
				break

			if not data.get("data"):
				self.extractor.log.debug("No data found in response")
				break

			# Yield each tweet in the current page
			for item in data["data"]:
				yield item

			# Check if there's a next page
			current_page = data.get("current", 1)
			next_page = data.get("next")

			if not next_page or next_page <= current_page:
				break

			page_no = next_page
