# -*- coding: utf-8 -*-
"""
    The actual implementation of the SQLAlchemy data layer.

    :copyright: (c) 2013 by Andrew Mleczko and Tomasz Jezierski (Tefnet)
    :license: BSD, see LICENSE for more details.
"""
from __future__ import unicode_literals

import collections
import simplejson as json
import flask.ext.sqlalchemy as flask_sqlalchemy

from flask import abort
from copy import copy

from eve.io.base import ConnectionException
from eve.io.base import DataLayer
from eve.utils import config, debug_error_message, str_to_date
from .parser import parse, parse_dictionary, ParseError, sqla_op, parse_sorting
from .structures import SQLAResultCollection
from .utils import dict_update, validate_filters, sqla_object_to_dict, \
    extract_sort_arg, rename_relationship_fields_in_sort_args, \
    rename_relationship_fields_in_dict, rename_relationship_fields_in_str

__version__ = '0.1-dev'

db = flask_sqlalchemy.SQLAlchemy()

try:
    string_type = basestring
except NameError:
    # Python 3
    string_type = str


class SQL(DataLayer):
    """
    SQLAlchemy data access layer for Eve REST API.
    """
    driver = db
    serializers = {
        'datetime': str_to_date,
        'number': lambda val: json.loads(val) if val is not None else None,
    }

    def init_app(self, app):
        try:
            # FIXME: dumb double initialisation of the
            # driver because Eve sets it to None in __init__
            self.driver = db
            self.driver.app = app
            self.driver.init_app(app)
        except Exception as e:
            raise ConnectionException(e)

        self.register_schema(app)

    @classmethod
    def lookup_model(cls, model_name):
        """
        Lookup SQLAlchemy model class by its name

        :param model_name: Name of SQLAlchemy model.
        """
        return cls.driver.Model._decl_class_registry[model_name]

#    @classmethod
    def register_schema(self, app, model_name=None):
        """Register eve schema for SQLAlchemy model(s)
        :param app: Flask application instance.
        :param model_name: Name of SQLAlchemy model
            (register all models if not provided)
        """
        if model_name:
            models = {model_name.capitalize(): self.driver.
                      Model._decl_class_registry[model_name.capitalize()]}
        else:
            models = self.driver.Model._decl_class_registry

        for model_name, model_cls in models.items():
            if model_name.startswith('_'):
                continue
            if getattr(model_cls, '_eve_schema', None):
                eve_schema = model_cls._eve_schema
                dict_update(app.config['DOMAIN'], eve_schema)
                resource = list(eve_schema.keys())[0]
                model_cls._eve_schema[resource] = \
                    app.config['DOMAIN'][resource]

        for k, v in app.config['DOMAIN'].items():
            # If a resource has a relation, copy the properties of the relation
            if 'datasource' in v and 'source' in v['datasource']:
                source = v['datasource']['source']
                source = app.config['DOMAIN'].get(source.lower(), {})
                for key in ('schema', 'id_field', 'item_lookup_field',
                            'item_url'):
                    if key in source:
                        v[key] = source[key]
            # Even if the projection was set by the user, require that:
            # - the id field is included
            # - the ETag is excluded, as it will be added automatically if
            #   IF_MATCH is True
            if 'datasource' in v and 'projection' in v['datasource']:
                projection = v['datasource']['projection']
                projection[self._id_field(k)] = 1
                projection[config.ETAG] = 0
            else:
                projection = {config.ETAG: 0}

    def find(self, resource, req, sub_resource_lookup):
        """Retrieves a set of documents matching a given request. Queries can
        be expressed in two different formats: the mongo query syntax, and the
        python syntax. The first kind of query would look like: ::

            ?where={"name": "john doe}

        while the second would look like: ::

            ?where=name=="john doe"

        The resultset if paginated.

        :param resource: resource name.
        :param req: a :class:`ParsedRequest`instance.
        :param sub_resource_lookup: sub-resource lookup from the endpoint url.
        """
        try:
            args = {'sort': extract_sort_arg(req),
                    'resource': resource}
        except Exception as e:
            self.app.logger.exception(e)
            abort(400, description=debug_error_message(str(e)))

        client_projection = self._client_projection(req)
        client_embedded = self._client_or_config_embedded(req, resource)
        model, args['spec'], fields, args['sort'] = \
            self._datasource_ex(resource, [], client_projection,
                                args['sort'], client_embedded)
        if req.where:
            try:
                where = rename_relationship_fields_in_str(model, req.where)
                args['spec'] = self.combine_queries(args['spec'],
                                                    parse(where, model))
            except ParseError:
                try:
                    spec = rename_relationship_fields_in_dict(
                        model, json.loads(req.where))
                    args['spec'] = self.combine_queries(
                        args['spec'], parse_dictionary(spec, model))
                except (AttributeError, TypeError):
                    # if parse failed and json loads fails - raise 400
                    abort(400)

        bad_filter = validate_filters(args['spec'], resource)
        if bad_filter:
            abort(400, bad_filter)

        if sub_resource_lookup:
            sub_resource_lookup = rename_relationship_fields_in_dict(
                model, sub_resource_lookup)
            args['spec'] = \
                self.combine_queries(args['spec'],
                                     parse_dictionary(sub_resource_lookup,
                                                      model))

        if req.if_modified_since:
            updated_filter = sqla_op.gt(getattr(model, config.LAST_UPDATED),
                                        req.if_modified_since)
            args['spec'].append(updated_filter)

        query = self.driver.session.query(model)

        if args['sort']:
            ql = []
            for sort_item in args['sort']:
                ql.append(parse_sorting(model, query, *sort_item))
            args['sort'] = ql

        if req.max_results:
            args['max_results'] = req.max_results
        if req.page > 1:
            args['page'] = req.page
        return SQLAResultCollection(query, fields, **args)

    def find_one(self, resource, req, **lookup):
        client_projection = self._client_projection(req)
        client_embedded = self._client_or_config_embedded(req, resource)
        model, filter_, fields, _ = \
            self._datasource_ex(resource, [], client_projection, None,
                                client_embedded)

        lookup = rename_relationship_fields_in_dict(model, lookup)
        id_field = self._id_field(resource)
        if isinstance(lookup.get(id_field), dict) \
                or isinstance(lookup.get(id_field), list):
            # very dummy way to get the related object
            # that commes from embeddable parameter
            return lookup
        else:
            filter_ = self.combine_queries(filter_,
                                           parse_dictionary(lookup, model))
            query = self.driver.session.query(model)
            document = query.filter(*filter_).first()

        return sqla_object_to_dict(document, fields) if document else None

    def find_one_raw(self, resource, _id):
        model, filter_, fields, _ = \
            self._datasource_ex(resource, [], None, None, None)
        id_field = self._id_field(resource)
        lookup = {id_field: _id}
        filter_ = self.combine_queries(filter_,
                                       parse_dictionary(lookup, model))
        document = self.driver.session.query(model).filter(*filter_).first()
        return sqla_object_to_dict(document, fields) if document else None

    def find_list_of_ids(self, resource, ids, client_projection=None):
        raise NotImplementedError

    def insert(self, resource, doc_or_docs):
        rv = []
        for document in doc_or_docs:
            model_instance = self._create_model_instance(resource, document)
            self.driver.session.add(model_instance)
            self.driver.session.commit()
            id_field = self._id_field(resource)
            document[id_field] = getattr(model_instance, id_field)
            rv.append(document[id_field])
        return rv

    def _create_model_instance(self, resource, dict_):
        model, _, _, _ = self._datasource_ex(resource)
        schema = self.app.config['DOMAIN'][resource]['schema']
        fields = {}
        for field, value in dict_.items():
            if field in schema and 'data_relation' in schema[field]:
                if isinstance(value, collections.Mapping):
                    fields[field] = self._create_model_instance(
                        schema[field]['data_relation']['resource'], value)
                elif 'local_id_field' in schema[field]:
                    fields[schema[field]['local_id_field']] = value
            elif field in schema and schema[field]['type'] in ('list', 'set'):
                if 'schema' in schema[field] and \
                   'data_relation' in schema[field]['schema']:
                    sub_schema = schema[field]['schema']
                    contains_ids = False
                    list_ = []
                    for v in value:
                        if isinstance(v, collections.Mapping):
                            list_.append(self._create_model_instance(
                                sub_schema['data_relation']['resource'], v))
                        else:
                            contains_ids = True
                            list_.append(v)
                    collection = set(list_) \
                        if schema[field]['type'] == 'set' else list_
                    if contains_ids and 'local_id_field' in schema[field]:
                        fields[schema[field]['local_id_field']] = collection
                    else:
                        fields[field] = collection
                else:
                    fields[field] = value
            else:
                fields[field] = value
        return model(**fields)

    def replace(self, resource, id_, document, original):
        model, filter_, fields_, _ = self._datasource_ex(resource, [])
        id_field = self._id_field(resource)
        filter_ = self.combine_queries(filter_,
                                       parse_dictionary({id_field: id_}, model))
        query = self.driver.session.query(model)

        # Find and delete the old object
        old_model_instance = query.filter(*filter_).first()
        if old_model_instance is None:
            abort(500, description=debug_error_message('Object not existent'))
        self._handle_immutable_id(id_field, old_model_instance, document)
        self.driver.session.delete(old_model_instance)

        # create and insert the new one
        model_instance = self._create_model_instance(resource, document)
        id_field = self._id_field(resource)
        setattr(model_instance, id_field, id_)
        self.driver.session.add(model_instance)
        self.driver.session.commit()

    def update(self, resource, id_, updates, original):
        model, filter_, _, _ = self._datasource_ex(resource, [])
        id_field = self._id_field(resource)
        filter_ = self.combine_queries(filter_,
                                       parse_dictionary({id_field: id_}, model))
        query = self.driver.session.query(model)
        model_instance = query.filter(*filter_).first()
        if model_instance is None:
            abort(500, description=debug_error_message('Object not existent'))
        updates = rename_relationship_fields_in_dict(model, updates)
        self._handle_immutable_id(id_field, model_instance, updates)
        for k, v in updates.items():
            setattr(model_instance, k, v)
        self.driver.session.commit()

    def _handle_immutable_id(self, id_field, original_instance, updates):
        if id_field in updates and \
           getattr(original_instance, id_field) != updates[id_field]:
            description = \
                "Attempt to update an immutable field. Usually happens " \
                "when PATCH or PUT include a '%s' field, " \
                "which is immutable (PUT can include it as long as " \
                "it is unchanged)." % id_field
            abort(400, description=description)

    def remove(self, resource, lookup):
        model, filter_, _, _ = self._datasource_ex(resource, [])
        lookup = rename_relationship_fields_in_dict(model, lookup)
        filter_ = self.combine_queries(filter_,
                                       parse_dictionary(lookup, model))
        query = self.driver.session.query(model)
        if len(filter_):
            query = query.filter(*filter_)
        for item in query:
            self.driver.session.delete(item)

        self.driver.session.commit()

    def _source(self, resource):
        return self.driver.app.config['SOURCES'][resource]['source']

    def _id_field(self, resource):
        return self.driver.app.config['DOMAIN'][resource]['id_field']

    def _model(self, resource):
        return self.lookup_model(self._source(resource))

    def _parse_filter(self, model, filter):
        """
        Convert from Mongo/JSON style filters to SQLAlchemy expressions.
        """
        if filter is None or len(filter) == 0:
            filter = []
        elif isinstance(filter, string_type):
            filter = parse(filter, model)
        elif isinstance(filter, dict):
            filter = parse_dictionary(filter, model)
        elif not isinstance(filter, list):
            filter = []
        return filter

    def datasource(self, resource):
        """
        Overridden from super to return the actual model class of the database
        table instead of the name of it. We also parse the filter coming from
        the schema definition into a SQL compatible filter
        """
        model = self._model(resource)

        resource_def = self.driver.app.config['SOURCES'][resource]
        filter_ = resource_def['filter']
        filter_ = self._parse_filter(model, filter_)
        projection_ = copy(resource_def['projection'])
        sort_ = copy(resource_def['default_sort'])
        return model, filter_, projection_, sort_

    # NOTE(Gonéri): preserve the _datasource method for compatibiliy with
    # pre 0.6 Eve release (See: commit 87742343fd0362354b9f75c749651f92d6e4a9c8
    # from the Eve repository)
    def _datasource(self, resource):
        return self.datasource(resource)

    def _datasource_ex(self, resource, query=None, client_projection=None,
                       client_sort=None, client_embedded=None):
        model, filter_, fields_, sort_ = \
            super(SQL, self)._datasource_ex(resource, query, client_projection,
                                            client_sort)
        filter_ = self._parse_filter(model, filter_)
        fields = [field for field in fields_.keys() if fields_[field]]
        if sort_ is not None:
            sort_ = rename_relationship_fields_in_sort_args(model, sort_)
        return model, filter_, fields, sort_

    def combine_queries(self, query_a, query_b):
        # TODO: dumb concatenation of query lists.
        #       We really need to check for duplicate queries
        query_a.extend(query_b)
        return query_a

    def is_empty(self, resource):
        model, filter_, _, _ = self.datasource(resource)
        query = self.driver.session.query(model)
        if len(filter_):
            return query.filter_by(*filter_).count() == 0
        else:
            return query.count() == 0

    def _client_embedded(self, req):
        """ Returns a properly parsed client embeddable if available.

        :param req: a :class:`ParsedRequest` instance.

        .. versionadded:: 0.4
        """
        client_embedded = {}
        if req and req.embedded:
            try:
                client_embedded = json.loads(req.embedded)
            except:
                abort(400, description=debug_error_message(
                    'Unable to parse `embedded` clause'
                ))
        return client_embedded

    def _client_or_config_embedded(self, req, resource):
        """ Returns a properly parsed client embeddable if available - from request and from app resource config.
        :param req: a :class:`ParsedRequest` instance.
        :param resource: resource name
        .. versionadded:: 0.4
        """
        client_embedded = self._client_embedded(req)
        if 'embedded_fields' in config.DOMAIN[resource]:
            config_embedded = {key: 1 for key in config.DOMAIN[resource]['embedded_fields']}
            client_embedded.update(config_embedded)
        return client_embedded
