# -*- coding: utf-8 -*-

# Copyright 2016-2025 Mike Fährmann
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.

"""Extractors for https://www.uraaka-joshi.com/"""

from .common import Extractor, Message, Dispatch
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


class UraakajoshiUserExtractor(Dispatch, UraakajoshiExtractor):
	"""Extractor for Uraaka-joshi user profiles"""

	subcategory = "user"
	pattern = USER_PATTERN + r"/?(?:$|\?|#)"
	example = "https://www.uraaka-joshi.com/user/USERNAME"

	def items(self):
		base = f"{self.root}/user/{self.user}/"
		return self._dispatch_extractors(
			(
				(UraakajoshiInfoExtractor, base + "info"),
				(UraakajoshiTimelineExtractor, base + "timeline"),
				(UraakajoshiAvatarExtractor, base + "avatar"),
				(UraakajoshiBackgroundExtractor, base + "background"),
			),
			("timeline",),
		)


class UraakajoshiTimelineExtractor(UraakajoshiExtractor):
	"""Extractor for a Uraaka-joshi user timeline"""

	subcategory = "timeline"
	pattern = USER_PATTERN + r"/timeline/?(?:$|\?|#)"
	example = "https://www.uraaka-joshi.com/user/USERNAME/timeline"

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


class UraakajoshiInfoExtractor(UraakajoshiExtractor):
	"""Extractor for Uraaka-joshi user profile information"""

	subcategory = "info"
	pattern = USER_PATTERN + r"/info/?(?:$|\?|#)"
	example = "https://www.uraaka-joshi.com/user/USERNAME/info"

	def items(self):
		self.api = UraakajoshiAPI(self)

		# Get user data from first tweet if available
		user_data = None
		for tweet_data in self.api.user_timeline(self.user, max_pages=1):
			user_data = self._transform_tweet(tweet_data)["user"]
			break

		if user_data:
			yield Message.Directory, {"user": user_data}

	def metadata(self):
		"""Return user metadata"""
		if not hasattr(self, "api"):
			self.api = UraakajoshiAPI(self)

		user_data = None
		for tweet_data in self.api.user_timeline(self.user, max_pages=1):
			user_data = self._transform_tweet(tweet_data)["user"]
			break

		return {"user": user_data} if user_data else {}


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


class UraakajoshiAvatarExtractor(UraakajoshiExtractor):
	"""Extractor for Uraaka-joshi user avatars"""

	subcategory = "avatar"
	pattern = USER_PATTERN + r"/avatar"
	example = "https://www.uraaka-joshi.com/user/USERNAME/avatar"
	filename_fmt = "avatar_{filename}.{extension}"
	archive_fmt = "avatar_{filename}"

	def items(self):
		"""Fetch user avatars"""
		if not self.user:
			return

		self.api = UraakajoshiAPI(self)

		# Get user data from first tweet if available
		tweet_data = None
		user_data = None
		for tweet_data in self.api.user_timeline(self.user, max_pages=1):
			user_data = self._transform_tweet(tweet_data)["user"]
			break

		if not user_data or not tweet_data:
			return

		yield Message.Directory, {"user": user_data}

		# Process avatars from screen_name array
		screen_names = tweet_data.get("screen_name", [])
		if not screen_names:
			return

		# Remove duplicates based on avatar_file_name
		seen_avatars = set()
		unique_screen_names = []
		for screen_name_data in screen_names:
			avatar_filename = screen_name_data.get("avatar_file_name")
			if avatar_filename and avatar_filename not in seen_avatars:
				seen_avatars.add(avatar_filename)
				unique_screen_names.append(screen_name_data)

		for num, screen_name_data in enumerate(unique_screen_names, 1):
			avatar_filename = screen_name_data.get("avatar_file_name")
			if not avatar_filename:
				self.log.debug(
					"Skipping avatar for %s: no avatar_file_name",
					screen_name_data.get("screen_name", "unknown"),
				)
				continue

			username = screen_name_data["screen_name"]
			first_char = username[0]

			# Construct avatar URL
			avatar_url = (
				f"{self.root}/media/{first_char}/{username}/profile/{avatar_filename}"
			)

			# Detect extension from filename
			extension = (
				avatar_filename.split(".")[-1].lower() if "." in avatar_filename else "jpg"
			)

			yield (
				Message.Url,
				avatar_url,
				{
					"extension": extension,
					"filename": avatar_filename.rsplit(".", 1)[0]
					if "." in avatar_filename
					else avatar_filename,
					"media_id": f"avatar_{username}",
					"type": "avatar",
					"tweet_id": 0,
					"num": num,
					"screen_name": username,
					"user": user_data,
				},
			)

	def metadata(self):
		"""Return user metadata"""
		if not hasattr(self, "api"):
			self.api = UraakajoshiAPI(self)

		user_data = None
		for tweet_data in self.api.user_timeline(self.user, max_pages=1):
			user_data = self._transform_tweet(tweet_data)["user"]
			break

		return {"user": user_data} if user_data else {}


class UraakajoshiBackgroundExtractor(UraakajoshiExtractor):
	"""Extractor for Uraaka-joshi user background images"""

	subcategory = "background"
	pattern = USER_PATTERN + r"/background"
	example = "https://www.uraaka-joshi.com/user/USERNAME/background"
	filename_fmt = "background_{filename}.{extension}"
	archive_fmt = "background_{filename}"

	def items(self):
		"""Fetch user background images"""
		if not self.user:
			return

		self.api = UraakajoshiAPI(self)

		# Get user data from first tweet if available
		tweet_data = None
		user_data = None
		for tweet_data in self.api.user_timeline(self.user, max_pages=1):
			user_data = self._transform_tweet(tweet_data)["user"]
			break

		if not user_data or not tweet_data:
			return

		yield Message.Directory, {"user": user_data}

		# Process backgrounds from screen_name array
		screen_names = tweet_data.get("screen_name", [])
		if not screen_names:
			return

		# Remove duplicates based on banner_file_name
		seen_banners = set()
		unique_screen_names = []
		for screen_name_data in screen_names:
			banner_filename = screen_name_data.get("banner_file_name")
			if banner_filename and banner_filename not in seen_banners:
				seen_banners.add(banner_filename)
				unique_screen_names.append(screen_name_data)

		for num, screen_name_data in enumerate(unique_screen_names, 1):
			banner_filename = screen_name_data.get("banner_file_name")
			if not banner_filename:
				self.log.debug(
					"Skipping background for %s: no banner_file_name",
					screen_name_data.get("screen_name", "unknown"),
				)
				continue

			username = screen_name_data["screen_name"]
			first_char = username[0]

			# Construct background image URL
			background_url = (
				f"{self.root}/media/{first_char}/{username}/profile/{banner_filename}"
			)

			# Detect extension from filename
			extension = (
				banner_filename.split(".")[-1].lower() if "." in banner_filename else "jpg"
			)

			yield (
				Message.Url,
				background_url,
				{
					"extension": extension,
					"filename": banner_filename.rsplit(".", 1)[0]
					if "." in banner_filename
					else banner_filename,
					"media_id": f"background_{username}",
					"type": "background",
					"tweet_id": 0,
					"num": num,
					"screen_name": username,
					"user": user_data,
				},
			)

	def metadata(self):
		"""Return user metadata"""
		if not hasattr(self, "api"):
			self.api = UraakajoshiAPI(self)

		user_data = None
		for tweet_data in self.api.user_timeline(self.user, max_pages=1):
			user_data = self._transform_tweet(tweet_data)["user"]
			break

		return {"user": user_data} if user_data else {}


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
