# -*- coding: utf-8 -*-

import logging
import json
from urlparse import urlsplit, urljoin

import requests
import parsel

from patient import Patient
from study import Study
from utils import get_from_nested_dict


class PACS(object):
    """
    Base class to consume data from the API
    """

    def __repr__(self):
        return '<PACS object. host: "{}", port: "{}", aet="{}">'.format(self.host, self.port, self.aet)

    def __init__(self, schema='http', host='localhost', port='8080', aet='DCM4CHEE',
                 user=None, password=None, log_urls=False):
        self.schema = schema
        self.aet = aet
        self.host = host
        self.port = port
        self.log_urls = log_urls  # for debugging
        self.user = user
        self.password = password
        if self.log_urls:
            logger = logging.getLogger()
            logger.setLevel(logging.INFO)
        self.base_rs_url = '{}://{}:{}/dcm4chee-arc/aets/{}/rs/'.format(
            self.schema, self.host, self.port, self.aet
        )
        self.base_wado_url = '{}://{}:{}/dcm4chee-arc/aets/{}/wado/'.format(
            self.schema, self.host, self.port, self.aet
        )
        self.session = requests.Session()
        # determine if the api needs auth
        resp = self._make_request(service='rs', path='studies', params={'limit': 1})
        if '/auth/realms' in urlsplit(resp.url).path:
            self.authorize(resp)

    def authorize(self, response):
        sel = parsel.Selector(response.text)
        post_url = sel.css('form::attr(action)').extract_first()
        resp = self.session.post(post_url, data={'username': self.user, 'password': self.password})
        if '/auth/realms' in resp.url:
            raise Exception('Failed auth')

    def get_patients(self, offset=0, limit=50, orderby=None, filter_attributes=None):
        patient_list = []
        if type(filter_attributes) is not dict:
            filter_attributes = {}
        filter_attributes['limit'] = limit
        filter_attributes['offset'] = offset
        filter_attributes['orderby'] = orderby
        for json_patient in self._make_request(path='patients', params=filter_attributes):
            patient_list.append(Patient(pacs=self, input_dict=json_patient))
        return patient_list

    def get_studies(self, bind_to_patient=None, offset=0, limit=50, orderby=None, filter_attributes=None):
        study_list = []
        if type(filter_attributes) is not dict:
            filter_attributes = {}
        filter_attributes['limit'] = limit
        filter_attributes['offset'] = offset
        filter_attributes['orderby'] = orderby
        for json_study in self._make_request(path='studies', params=filter_attributes):
            # get patient object
            if bind_to_patient and type(bind_to_patient) is Patient:
                patient = bind_to_patient
            else:
                filter_patient = {
                    'PatientID': get_from_nested_dict(json_study, ['00100020', 'Value', 0]),
                    'PatientName': get_from_nested_dict(json_study, ['00100010', 'Value', 0, 'Alphabetic']),
                }
                result = self.get_patients(limit=1, filter_attributes=filter_patient)
                patient = result[0] if len(result) > 0 else None
            # create study object
            study_list.append(Study(pacs=self, patient=patient, input_dict=json_study))
        return study_list

    def _make_request(self, path='', service='rs', method='GET', headers=None, params=None):
        if service not in ('rs', 'wado'):
            service = 'rs'

        if headers is None:
            headers = {}
        if params is None:
            params = {}

        base_url = self.base_rs_url if service == 'rs' else self.base_wado_url
        stream = True if service == 'wado' else False
        if path and path[0] == '/':
            path = path[1:]
        url = urljoin(base_url, path)
        resp = self.session.request(method=method, url=url, params=params, headers=headers, stream=stream)
        if self.log_urls:
            logging.info('Response URL: {}'.format(resp.url))

        if resp.status_code == 200:
            if resp.headers.get('Content-Type') == 'application/json':
                try:
                    return resp.json()
                except ValueError:
                    return []
            else:
                return resp
        else:
            raise Exception('Non-200 response for {} (status: {})'.format(resp.url, resp.status_code))
