# -*- coding: utf-8 -*-

# Copyright 2016-2025 Mike Fährmann
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.

"""Extractors for https://www.uraaka-joshi.com/"""

from .common import Extractor, Message, Dispatch
from .. import text, util
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
		self.username = match[1] if match else None
		self._cached_user_data = None
		self._cursor = None

	def items(self):
		self.api = UraakajoshiAPI(self)

		for tweet_data in self.tweets():
			transformed_tweet = self._transform_tweet(tweet_data)
			media_files = self._extract_media_files(tweet_data)

			if not media_files:
				continue

			yield Message.Directory, transformed_tweet

			for file_number, file_metadata in enumerate(media_files, 1):
				url = file_metadata.pop("_url")
				file_metadata.update(transformed_tweet)
				file_metadata["num"] = file_number
				yield Message.Url, url, file_metadata

	def _extract_media_files(self, data):
		"""Extract media files from tweet data"""
		if not self._has_media(data):
			return []

		username = data["user"]["screen_name"]
		date_folder, timestamp_folder = self._extract_date_folders(data["tweet"]["created"])

		return [
			file_metadata
			for media in data["media"]
			for file_metadata in self._create_media_metadata(
				media, username, date_folder, timestamp_folder
			)
		]

	def _has_media(self, data):
		"""Check if tweet data contains media"""
		return "media" in data and data["media"]

	def _extract_date_folders(self, created_timestamp):
		"""Extract date folder names from timestamp"""
		try:
			parsed_datetime = datetime.datetime.strptime(
				created_timestamp, "%Y-%m-%d %H:%M:%S"
			)
			return parsed_datetime.strftime("%Y%m"), parsed_datetime.strftime("%Y%m%d%H%M%S")
		except ValueError:
			return "unknown", "unknown"

	def _create_media_metadata(self, media, username, date_folder, timestamp_folder):
		"""Create metadata for a single media item"""
		files = []

		if media.get("video_file_name"):
			files.append(
				self._create_video_metadata(media, username, date_folder, timestamp_folder)
			)
		elif media.get("photo_file_name"):
			files.append(
				self._create_photo_metadata(media, username, date_folder, timestamp_folder)
			)

		return files

	def _create_video_metadata(self, media, username, date_folder, timestamp_folder):
		"""Create metadata for video file"""
		url = self._build_media_url(
			username, date_folder, timestamp_folder, media["video_file_name"]
		)
		return {
			"_url": url,
			"media_id": text.parse_int(media["id"]),
			"extension": self._get_file_extension(media["video_file_name"]),
			"type": "video",
		}

	def _create_photo_metadata(self, media, username, date_folder, timestamp_folder):
		"""Create metadata for photo file"""
		url = self._build_media_url(
			username, date_folder, timestamp_folder, media["photo_file_name"]
		)
		return {
			"_url": url,
			"media_id": text.parse_int(media["id"]),
			"width": media.get("photo_width", 0),
			"height": media.get("photo_height", 0),
			"extension": self._get_file_extension(media["photo_file_name"]),
			"type": "photo",
		}

	def _build_media_url(self, username, date_folder, timestamp_folder, filename):
		"""Build complete media URL"""
		first_char = username[0]
		return f"{self.root}/media/{first_char}/{username}/{date_folder}/{timestamp_folder}/{filename}"

	def _get_file_extension(self, filename):
		"""Extract file extension from filename"""
		return filename.split(".")[-1] if "." in filename else ""

	def _transform_tweet(self, data):
		"""Transform API data into standardized tweet format"""
		return {
			**self._transform_tweet_data(data["tweet"]),
			"user": self._transform_user_data(data["user"]),
			"screen_name": data["screen_name"],
		}

	def _transform_user_data(self, user_data):
		"""Transform user data into standardized format"""
		return {
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

	def _transform_tweet_data(self, tweet_data):
		"""Transform tweet data into standardized format"""
		tweet_id = text.parse_int(tweet_data["id"])
		return {
			"tweet_id": tweet_id,
			"id": tweet_id,
			"content": text.unescape(tweet_data["text"]),
			"date": self.parse_timestamp(tweet_data["created"], "%Y-%m-%d %H:%M:%S"),
			"created": tweet_data["created"],
			"type": tweet_data.get("type", ""),
			"access_ranking": tweet_data.get("access_ranking", ""),
		}

	def _get_user_data_from_timeline(self):
		"""Get user data from the first tweet in timeline"""
		if not hasattr(self, "api"):
			self.api = UraakajoshiAPI(self)

		for tweet_data in self.api.user_timeline(self.username, max_pages=1):
			return self._transform_tweet(tweet_data)["user"]
		return None

	def _get_first_tweet_data(self):
		"""Get the first tweet data from timeline"""
		if not hasattr(self, "api"):
			self.api = UraakajoshiAPI(self)

		for tweet_data in self.api.user_timeline(self.username, max_pages=1):
			return tweet_data
		return None

	def _extract_unique_profile_media(self, screen_names, file_key, media_type):
		"""Extract unique profile media files (avatars/backgrounds)"""
		seen_files = set()
		unique_items = []

		for screen_name_data in screen_names:
			filename = screen_name_data.get(file_key)
			if filename and filename not in seen_files:
				seen_files.add(filename)
				unique_items.append((screen_name_data, filename))

		return unique_items

	def _create_profile_media_metadata(
		self, username, filename, media_type, file_number, user_data
	):
		"""Create metadata for profile media files"""
		extension = filename.split(".")[-1].lower() if "." in filename else "jpg"
		base_filename = filename.rsplit(".", 1)[0] if "." in filename else filename

		return {
			"extension": extension,
			"filename": base_filename,
			"media_id": f"{media_type}_{username}",
			"type": media_type,
			"tweet_id": 0,
			"num": file_number,
			"screen_name": username,
			"user": user_data,
		}

	def _build_profile_media_url(self, username, filename):
		"""Build URL for profile media (avatar/background)"""
		first_char = username[0]
		return f"{self.root}/media/{first_char}/{username}/profile/{filename}"

	def tweets(self):
		"""Generate tweet data - to be overridden by subclasses"""
		return []

	def metadata(self):
		"""Return metadata for the extraction"""
		return {}

	def finalize(self):
		"""Log cursor information for continuing downloads"""
		if self._cursor:
			self.log.info(
				"Use '-o cursor=%s' to continue downloading from the current position",
				self._cursor,
			)

	def _init_cursor(self):
		"""Initialize cursor from config"""
		cursor = self.config("cursor", True)
		if cursor is True:
			return None
		elif not cursor:
			self._update_cursor = util.identity
		return cursor

	def _update_cursor(self, cursor):
		"""Update cursor and log debug information"""
		if cursor:
			self.log.debug("Cursor: %s", cursor)
		self._cursor = cursor
		return cursor


class UraakajoshiUserExtractor(Dispatch, UraakajoshiExtractor):
	"""Extractor for Uraaka-joshi user profiles"""

	subcategory = "user"
	pattern = USER_PATTERN + r"/?(?:$|\?|#)"
	example = "https://www.uraaka-joshi.com/user/USERNAME"

	def items(self):
		base = f"{self.root}/user/{self.username}/"
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
		return self.api.user_timeline(self.username)

	def metadata(self):
		"""Return user metadata"""
		if self._cached_user_data is None:
			self._cached_user_data = self._get_user_data_from_timeline()

		return {"user": self._cached_user_data} if self._cached_user_data else {}


class UraakajoshiInfoExtractor(UraakajoshiExtractor):
	"""Extractor for Uraaka-joshi user profile information"""

	subcategory = "info"
	pattern = USER_PATTERN + r"/info/?(?:$|\?|#)"
	example = "https://www.uraaka-joshi.com/user/USERNAME/info"

	def items(self):
		user_data = self._get_user_data_from_timeline()
		if user_data:
			yield Message.Directory, {"user": user_data}

	def metadata(self):
		"""Return user metadata"""
		user_data = self._get_user_data_from_timeline()
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

		for tweet_data in self.api.hashtag_timeline(
			self.tag, page_start=self.page_start, cursor=self._init_cursor()
		):
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
		if not self.username:
			return

		tweet_data = self._get_first_tweet_data()
		user_data = self._get_user_data_from_timeline()

		if not user_data or not tweet_data:
			return

		yield Message.Directory, {"user": user_data}

		screen_names = tweet_data.get("screen_name", [])
		if not screen_names:
			return

		unique_avatars = self._extract_unique_profile_media(
			screen_names, "avatar_file_name", "avatar"
		)

		for file_number, (screen_name_data, avatar_filename) in enumerate(
			unique_avatars, 1
		):
			username = screen_name_data["screen_name"]
			avatar_url = self._build_profile_media_url(username, avatar_filename)

			file_metadata = self._create_profile_media_metadata(
				username, avatar_filename, "avatar", file_number, user_data
			)

			yield Message.Url, avatar_url, file_metadata

	def metadata(self):
		"""Return user metadata"""
		user_data = self._get_user_data_from_timeline()
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
		if not self.username:
			return

		tweet_data = self._get_first_tweet_data()
		user_data = self._get_user_data_from_timeline()

		if not user_data or not tweet_data:
			return

		yield Message.Directory, {"user": user_data}

		screen_names = tweet_data.get("screen_name", [])
		if not screen_names:
			return

		unique_backgrounds = self._extract_unique_profile_media(
			screen_names, "banner_file_name", "background"
		)

		for file_number, (screen_name_data, banner_filename) in enumerate(
			unique_backgrounds, 1
		):
			username = screen_name_data["screen_name"]
			background_url = self._build_profile_media_url(username, banner_filename)

			file_metadata = self._create_profile_media_metadata(
				username, banner_filename, "background", file_number, user_data
			)

			yield Message.Url, background_url, file_metadata

	def metadata(self):
		"""Return user metadata"""
		user_data = self._get_user_data_from_timeline()
		return {"user": user_data} if user_data else {}


class UraakajoshiAPI:
	"""API handler for Uraaka-joshi"""

	def __init__(self, extractor):
		self.extractor = extractor
		self.root = extractor.root

	def user_timeline(self, username, max_pages=None):
		"""Fetch user timeline with pagination"""
		params = {
			"json_item": "user",
			"json_val": username,
			"one_char": username[0],
		}
		return self._fetch_timeline(params, max_pages, page_start=1)

	def _calculate_page_name(self, page_no):
		"""Calculate page_name based on page number"""
		page_name_number = (page_no // 1000) * 1000 + 999
		return f"{page_name_number:06d}"

	def _build_request_params(self, base_params, page_no):
		"""Build complete request parameters"""
		current_time = datetime.datetime.now().strftime("%Y%m%d%H%M")

		return {
			**base_params,
			"page_name": self._calculate_page_name(page_no),
			"page_no": str(page_no),
			"time": current_time,
		}

	def _make_timeline_request(self, params):
		"""Make timeline API request and return parsed data"""
		url = f"{self.root}/json/timeline/"
		response = self.extractor.request(url, params=params)

		try:
			return response.json()
		except Exception as exc:
			self.extractor.log.debug("Failed to parse JSON response: %s", exc)
			return None

	def _fetch_timeline(self, base_params, max_pages=None, page_start=1):
		"""Generic method to fetch timeline with pagination"""
		page_no = page_start

		while True:
			if max_pages and page_no > (page_start + max_pages - 1):
				break

			params = self._build_request_params(base_params, page_no)
			data = self._make_timeline_request(params)

			if not data or not data.get("data"):
				self.extractor.log.debug("No data found in response")
				self.extractor._update_cursor(None)
				break

			for item in data["data"]:
				yield item

			if not self._has_next_page(data):
				self.extractor._update_cursor(None)
				break

			page_no = data.get("next", page_no + 1)
			self.extractor._update_cursor(page_no)

	def _has_next_page(self, data):
		"""Check if there's a next page available"""
		current_page = data.get("current", 1)
		next_page = data.get("next")
		return next_page and next_page > current_page

	def hashtag_timeline(self, hashtag, max_pages=None, page_start=1, cursor=None):
		"""Fetch hashtag timeline with pagination"""
		params = {
			"json_item": "hashtag",
			"json_val": hashtag,
		}
		if cursor is not None:
			page_start = cursor
		return self._fetch_timeline(params, max_pages, page_start)
