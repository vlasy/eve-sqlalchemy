# -*- coding: utf-8 -*-

import random
import os
import string
import eve
from datetime import datetime
from unittest import TestCase
from sqlalchemy.sql.elements import BooleanClauseList
from operator import and_, or_
from eve.utils import str_to_date
from eve_sqlalchemy.tests.test_sql_tables import People
from eve_sqlalchemy.parser import parse
from eve_sqlalchemy.parser import parse_dictionary
from eve_sqlalchemy.parser import parse_sorting
from eve_sqlalchemy.parser import ParseError
from eve_sqlalchemy.parser import sqla_op

from eve_sqlalchemy.structures import SQLAResultCollection
from eve_sqlalchemy import SQL


class TestSQLParser(TestCase):

    def setUp(self):
        self.model = People

    def test_wrong_attribute(self):
        self.assertRaises(AttributeError, parse, 'a == 1', self.model)

    def test_eq(self):
        expected_expression = sqla_op.eq(self.model.firstname, 'john')
        r = parse('firstname == john', self.model)
        self.assertEqual(type(r), list)
        self.assertTrue(len(r) == 1)
        self.assertTrue(expected_expression.compare(r[0]))

    def test_gt(self):
        expected_expression = sqla_op.gt(self.model.prog, 5)
        r = parse('prog > 5', self.model)
        self.assertEqual(type(r), list)
        self.assertTrue(len(r) == 1)
        self.assertTrue(expected_expression.compare(r[0]))

    def test_gte(self):
        expected_expression = sqla_op.ge(self.model.prog, 5)
        r = parse('prog >= 5', self.model)
        self.assertEqual(type(r), list)
        self.assertTrue(len(r) == 1)
        self.assertTrue(expected_expression.compare(r[0]))

    def test_lt(self):
        expected_expression = sqla_op.lt(self.model.prog, 5)
        r = parse('prog < 5', self.model)
        self.assertEqual(type(r), list)
        self.assertTrue(len(r) == 1)
        self.assertTrue(expected_expression.compare(r[0]))

    def test_lte(self):
        expected_expression = sqla_op.le(self.model.prog, 5)
        r = parse('prog <= 5', self.model)
        self.assertEqual(type(r), list)
        self.assertTrue(len(r) == 1)
        self.assertTrue(expected_expression.compare(r[0]))

    def test_not_eq(self):
        expected_expression = sqla_op.ne(self.model.prog, 5)
        r = parse('prog != 5', self.model)
        self.assertEqual(type(r), list)
        self.assertTrue(len(r) == 1)
        self.assertTrue(expected_expression.compare(r[0]))

    def test_and_bool_op(self):
        r = parse('firstname == "john" and prog == 5', self.model)
        self.assertEqual(type(r), list)
        self.assertEqual(type(r[0]), BooleanClauseList)
        self.assertEqual(r[0].operator, and_)
        self.assertEqual(len(r[0].clauses), 2)
        expected_expression = sqla_op.eq(self.model.firstname, 'john')
        self.assertTrue(expected_expression.compare(r[0].clauses[0]))
        expected_expression = sqla_op.eq(self.model.prog, 5)
        self.assertTrue(expected_expression.compare(r[0].clauses[1]))

    def test_or_bool_op(self):
        r = parse('firstname == "john" or prog == 5', self.model)
        self.assertEqual(type(r), list)
        self.assertEqual(type(r[0]), BooleanClauseList)
        self.assertEqual(r[0].operator, or_)
        self.assertEqual(len(r[0].clauses), 2)
        expected_expression = sqla_op.eq(self.model.firstname, 'john')
        self.assertTrue(expected_expression.compare(r[0].clauses[0]))
        expected_expression = sqla_op.eq(self.model.prog, 5)
        self.assertTrue(expected_expression.compare(r[0].clauses[1]))

    def test_nested_bool_op(self):
        r = parse('firstname == "john" or (prog == 5 and lastname == "smith")',
                  self.model)
        self.assertEqual(type(r), list)
        self.assertEqual(type(r[0]), BooleanClauseList)
        self.assertEqual(r[0].operator, or_)
        self.assertEqual(len(r[0].clauses), 2)
        expected_expression = sqla_op.eq(self.model.firstname, 'john')
        self.assertTrue(expected_expression.compare(r[0].clauses[0]))
        second_op = r[0].clauses[1]
        self.assertEqual(type(second_op), BooleanClauseList)
        self.assertEqual(second_op.operator, and_)
        self.assertEqual(len(second_op.clauses), 2)
        expected_expression = sqla_op.eq(self.model.prog, 5)
        self.assertTrue(expected_expression.compare(second_op.clauses[0]))
        expected_expression = sqla_op.eq(self.model.lastname, 'smith')
        self.assertTrue(expected_expression.compare(second_op.clauses[1]))

    def test_raises_parse_error_for_invalid_queries(self):
        self.assertRaises(ParseError, parse, '', self.model)
        self.assertRaises(ParseError, parse, 'firstname', self.model)

    def test_raises_parse_error_for_invalid_op(self):
        self.assertRaises(ParseError, parse, 'firstname | "john"', self.model)

    def test_parse_string_to_date(self):
        expected_expression = \
            sqla_op.gt(self.model._updated,
                       str_to_date('Sun, 06 Nov 1994 08:49:37 GMT'))
        r = parse('_updated > "Sun, 06 Nov 1994 08:49:37 GMT"', self.model)
        self.assertEqual(type(r), list)
        self.assertTrue(len(r) == 1)
        self.assertTrue(expected_expression.compare(r[0]))

    def test_parse_dictionary(self):
        r = parse_dictionary({'firstname': 'john', 'prog': 5}, self.model)
        self.assertEqual(type(r), list)
        self.assertTrue(len(r) == 2)
        expected_expression = sqla_op.eq(self.model.firstname, 'john')
        any_true = any(expected_expression.compare(elem) for elem in r)
        self.assertTrue(any_true)
        expected_expression = sqla_op.eq(self.model.prog, 5)
        any_true = any(expected_expression.compare(elem) for elem in r)
        self.assertTrue(any_true)

    def test_parse_adv_dictionary(self):
        r = parse_dictionary({'firstname': ['john', 'dylan']}, self.model)
        self.assertEqual(str(r[0]),
                         'people.firstname IN (:firstname_1, :firstname_2)')

    def test_parse_sqla_operators(self):
        r = parse_dictionary({'firstname': 'ilike("john%")'}, self.model)
        self.assertEqual(str(r[0]),
                         'lower(people.firstname) LIKE lower(:firstname_1)')

        r = parse_dictionary({'firstname': 'like("john%")'}, self.model)
        self.assertEqual(str(r[0]),
                         'people.firstname LIKE :firstname_1')

        r = parse_dictionary({'firstname': 'in("(\'john\',\'mark\')")'},
                             self.model)
        self.assertEqual(str(r[0]),
                         'people.firstname in :firstname_1')
        self.assertEqual(r[0].right.value,
                         "('john','mark')")

        r = parse_dictionary({'firstname': 'similar to("(\'john%\'|\'mark%\')")'},
                             self.model)
        self.assertEqual(str(r[0]),
                         'people.firstname similar to :firstname_1')
        self.assertEqual(r[0].right.value,
                         "('john%'|'mark%')")

    def test_parse_sqla_and_or_conjunctions(self):
        r = parse_dictionary(
            {'or_': '[{"firstname": "john"}, {"and_": ['
             '{"firstname": "dylan"},{"lastname": "smith"}]}]'}, self.model)
        self.assertEqual(str(r[0]),
                         'people.firstname = :firstname_1 OR '
                         'people.firstname = :firstname_2 AND '
                         'people.lastname = :lastname_1')
        self.assertEqual(type(r), list)
        self.assertEqual(type(r[0]), BooleanClauseList)
        self.assertEqual(r[0].operator, or_)
        self.assertEqual(len(r[0].clauses), 2)
        expected_expression = sqla_op.eq(self.model.firstname, 'john')
        self.assertTrue(expected_expression.compare(r[0].clauses[0]))
        second_op = r[0].clauses[1]
        self.assertEqual(type(second_op), BooleanClauseList)
        self.assertEqual(second_op.operator, and_)
        self.assertEqual(len(second_op.clauses), 2)
        expected_expression = sqla_op.eq(self.model.firstname, 'dylan')
        self.assertTrue(expected_expression.compare(second_op.clauses[0]))
        expected_expression = sqla_op.eq(self.model.lastname, 'smith')
        self.assertTrue(expected_expression.compare(second_op.clauses[1]))


class TestSQLStructures(TestCase):

    def setUp(self):
        self.person = People(firstname='douglas', lastname='adams', prog=5,
                             _id=1, _updated=datetime.now(),
                             _created=datetime.now())

        self.fields = ['_id', '_updated', '_created', 'firstname', 'lastname',
                       'prog', '_etag']
        self.known_resource_count = 101
        self.max_results = 25

    def test_sql_collection(self):
        self.setupDB()
        c = SQLAResultCollection(self.query, self.fields)
        self.assertEqual(c.count(), self.known_resource_count)
        self.dropDB()

    def test_sql_collection_pagination(self):
        self.setupDB()
        with self.app.app_context():
            c = SQLAResultCollection(self.query, self.fields,
                                     max_results=self.max_results)
            self.assertEqual(c.count(), self.known_resource_count)
            results = [p for p in c]
            self.assertEqual(len(results), self.max_results)
        self.dropDB()

    def test_base_sorting(self):
        self.setupDB()
        self.assertEqual(str(
            parse_sorting(People, self.query, 'lastname', -1)).lower(),
            'people.lastname desc')
        self.assertEqual(str(
            parse_sorting(People, self.query, 'lastname', 1)).lower(),
            'people.lastname')
        self.assertEqual(str(
            parse_sorting(People, self.query, 'lastname', -1, 'nullslast')).lower(),
            'people.lastname desc nulls last')
        self.assertEqual(str(
            parse_sorting(People, self.query, 'lastname', -1, 'nullsfirst')).lower(),
            'people.lastname desc nulls first')

    def setupDB(self):
        self.this_directory = os.path.dirname(os.path.realpath(__file__))
        self.settings_file = os.path.join(self.this_directory,
                                          'test_settings_sql.py')
        self.app = eve.Eve(settings=self.settings_file, data=SQL)
        self.connection = SQL.driver
        self.connection.drop_all()
        self.connection.create_all()
        self.bulk_insert()
        self.query = self.connection.session.query(People)

    def bulk_insert(self):
        if not self.connection.session.query(People).count():
            # load random people in db
            people = self.random_people(self.known_resource_count)
            people = [People.from_tuple(item) for item in people]
            for person in people:
                self.connection.session.add(person)
            self.connection.session.commit()

    def random_string(self, length=6):
        return ''.join(random.choice(string.ascii_lowercase)
                       for _ in range(length)).capitalize()

    def random_people(self, num):
        people = []
        for i in range(num):
            people.append((self.random_string(6), self.random_string(6), i))
        return people

    def dropDB(self):
        self.connection = SQL.driver
        self.connection.session.remove()
        self.connection.drop_all()


# TODO: Validation tests
# class TestSQLValidator(TestCase):
#     def test_unique_fail(self):
#         """ relying on POST and PATCH tests since we don't have an active
#         app_context running here """
#         pass
#
#     def test_unique_success(self):
#         """ relying on POST and PATCH tests since we don't have an active
#         app_context running here """
#         pass
#
#     def test_objectid_fail(self):
#         schema = {'id': {'type': 'objectid'}}
#         doc = {'id': 'not_an_object_id'}
#         v = Validator(schema, None)
#         self.assertFalse(v.validate(doc))
#         self.assertTrue('id' in v.errors)
#         self.assertTrue('ObjectId' in v.errors['id'])
#
#     def test_objectid_success(self):
#         schema = {'id': {'type': 'objectid'}}
#         doc = {'id': ObjectId('50656e4538345b39dd0414f0')}
#         v = Validator(schema, None)
#         self.assertTrue(v.validate(doc))
#
#     def test_transparent_rules(self):
#         schema = {'a_field': {'type': 'string'}}
#         v = Validator(schema)
#         self.assertTrue(v.transparent_schema_rules, True)
