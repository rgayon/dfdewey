# -*- coding: utf-8 -*-
# Copyright 2020 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Elasticsearch datastore."""

import codecs
import collections
import logging

from elasticsearch import Elasticsearch
from elasticsearch import exceptions
import six

# Setup logging
es_logger = logging.getLogger('elasticsearch')
es_logger.addHandler(logging.NullHandler())
es_logger.setLevel(logging.WARNING)


class ElasticsearchDataStore(object):
  """Implements the datastore."""

  # Number of events to queue up when bulk inserting events.
  DEFAULT_FLUSH_INTERVAL = 20000
  DEFAULT_SIZE = 1000  # Max events to return

  def __init__(self, host='127.0.0.1', port=9200):
    """Create an Elasticsearch client."""
    super(ElasticsearchDataStore, self).__init__()
    self.client = Elasticsearch([{'host': host, 'port': port}])
    self.import_counter = collections.Counter()
    self.import_events = []

  def create_index(self, index_name):
    """Create an index.

    Args:
      index_name: Name of the index

    Returns:
      Index name in string format.
      Document type in string format.
    """
    if not self.client.indices.exists(index_name):
      try:
        self.client.indices.create(index=index_name)
      except exceptions.ConnectionError:
        raise RuntimeError('Unable to connect to backend datastore.')

    if not isinstance(index_name, six.text_type):
      index_name = codecs.decode(index_name, 'utf8')

    return index_name

  def delete_index(self, index_name):
    """Delete Elasticsearch index.

    Args:
      index_name: Name of the index to delete.
    """
    if self.client.indices.exists(index_name):
      try:
        self.client.indices.delete(index=index_name)
      except exceptions.ConnectionError as e:
        raise RuntimeError(
            'Unable to connect to backend datastore: {}'.format(e))

  def import_event(
      self, index_name, event=None,
      event_id=None, flush_interval=DEFAULT_FLUSH_INTERVAL):
    """Add event to Elasticsearch.

    Args:
      index_name: Name of the index in Elasticsearch
      event: Event dictionary
      event_id: Event Elasticsearch ID
      flush_interval: Number of events to queue up before indexing

    Returns:
      The number of events processed.
    """
    if event:
      for k, v in event.items():
        if not isinstance(k, six.text_type):
          k = codecs.decode(k, 'utf8')

        # Make sure we have decoded strings in the event dict.
        if isinstance(v, six.binary_type):
          v = codecs.decode(v, 'utf8')

        event[k] = v

      # Header needed by Elasticsearch when bulk inserting.
      header = {
          'index': {
              '_index': index_name
          }
      }
      update_header = {
          'update': {
              '_index': index_name,
              '_id': event_id
          }
      }

      if event_id:
        # Event has "lang" defined if there is a script used for import.
        if event.get('lang'):
          event = {'script': event}
        else:
          event = {'doc': event}
        header = update_header

      self.import_events.append(header)
      self.import_events.append(event)
      self.import_counter['events'] += 1

      if self.import_counter['events'] % int(flush_interval) == 0:
        self.client.bulk(body=self.import_events)
        self.import_events = []
    else:
      # Import the remaining events in the queue.
      if self.import_events:
        self.client.bulk(body=self.import_events)

    return self.import_counter['events']

  @staticmethod
  def build_query(query_string):
    """Build Elasticsearch DSL query.

    Args:
      query_string: Query string

    Returns:
      Elasticsearch DSL query as a dictionary
    """

    query_dsl = {
        'query': {
            'bool': {
                'must': [{
                    'query_string': {
                        'query': query_string
                    }
                }]
            }
        }
    }

    return query_dsl

  def search(self, index_id, query_string, size=DEFAULT_SIZE):
    """Search ElasticSearch.

    This will take a query string from the UI together with a filter definition.
    Based on this it will execute the search request on ElasticSearch and get
    the result back.

    Args:
      index_id: Index to be searched
      query_string: Query string
      size: Maximum number of results to return

    Returns:
      Set of event documents in JSON format
    """

    query_dsl = self.build_query(query_string)

    # Default search type for elasticsearch is query_then_fetch.
    search_type = 'query_then_fetch'

    return self.client.search(
        body=query_dsl,
        index=index_id,
        size=size,
        search_type=search_type)
