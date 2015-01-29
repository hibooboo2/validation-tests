import urlparse
from common_fixtures import *  # NOQA
from selenium import webdriver
from selenium.webdriver.phantomjs.service import Service as PhantomJSService
from requests.auth import AuthBase


# test the github auth workflow


class NewService(PhantomJSService):
    def __init__(self, *args, **kwargs):
        super(NewService, self).__init__(*args, **kwargs)
webdriver.phantomjs.webdriver.Service = NewService


if_github = pytest.mark.skipif(os.environ.get('API_AUTH_GITHUB'
                               '_TEST_USER') is None,
                               reason='API_AUTH_GITHUB_TEST_USER is not set')

BASE_URL = cattle_url() + '/v1/'
URL = BASE_URL + 'schemas'


@pytest.fixture(scope='module')
def github_request_code(user=None, pw=None):

    username = os.getenv('API_AUTH_GITHUB_TEST_USER', None)
    password = os.getenv('API_AUTH_GITHUB_TEST_PASS', None)
    phantomjs_port = int(os.getenv('PHANTOMJS_WEBDRIVER_PORT', 4444))
    phantomjs_bin = os.getenv('PHANTOMJS_BIN', '/usr/local/bin/phantomjs')

    if user is not None:
        username = user

    if pw is not None:
        password = pw

    driver = webdriver.PhantomJS(phantomjs_bin, port=phantomjs_port)
    max_wait = 60
    driver.set_page_load_timeout(max_wait)
    driver.set_script_timeout(max_wait)

    # undo monkey patching
    webdriver.phantomjs.webdriver.Service = PhantomJSService

    driver.set_window_size(1120, 550)
    client_id = os.getenv('API_AUTH_GITHUB_CLIENT_ID', None)

    if username is None or password is None or client_id is None:
        raise Exception('please set username, password and client_id in env')

    urlx = "https://github.com/login/oauth/authorize?client_id=" +\
           client_id + "&scope=read:org&state=random_string"
    driver.get(urlx)
    driver.find_element_by_id('login_field').send_keys(username)
    driver.find_element_by_id('password').send_keys(password)
    driver.find_element_by_name('commit').submit()
    cookie_dict = dict(driver.get_cookie('_gh_sess'))
    cookie_dict = {'_gh_sess': cookie_dict['value']}
    cookie_dict['user_session'] = driver.get_cookie('user_session')['value']
    r = None
    try:
        r = requests.get(urlx, cookies=cookie_dict, allow_redirects=False)
    except Exception as e:
        print e
    redirect_url = r.headers['location']
    query = urlparse.urlparse(redirect_url)[4]
    query = urlparse.parse_qs(query)
    driver.quit()
    return query['code']


@pytest.fixture(scope='module')
def github_client(cattle_url, github_request_token):
    github_client = from_env(url=cattle_url)
    assert  github_client.valid()
    jwt = github_request_token
    github_client._auth = GithubAuth(jwt)
    return github_client


class GithubAuth(AuthBase):
    def __init__(self, jwt):
        # setup any auth-related data here
        self.jwt = jwt

    def __call__(self, r):
        # modify and return the request
        r.headers['Authorization'] = 'Bearer '+ self.jwt
        return r


@pytest.fixture(scope='module')
def github_request_token(github_request_code):
    code = github_request_code

    c = requests.post(BASE_URL + 'token', {'code': code})

    return c.json()['jwt']


def switch_on_auth(github_client):
    github_client.create_githubconfig(enabled=True)


def switch_off_auth(github_client):
    github_client.create_githubconfig(enabled=False)


@if_github
def test_github_auth_config_unauth_user(github_client):
    switch_on_auth(github_client)
#   do not set any auth headers
    no_auth = requests.get(URL)

#   test that auth is switched on
    assert no_auth.status_code == 401

    switch_off_auth(github_client)


@if_github
def test_github_auth_config_invalid_user(github_client):
    switch_on_auth(github_client)

#   set invalid auth headers
    bad_auth = requests.get(URL,
                            headers={'Authorization':
                                     'Bearer some_random_string'})

#   test that user does not have access
    assert bad_auth.status_code == 401

    switch_off_auth(github_client)


@if_github
def test_github_auth_config_valid_user(github_client, github_request_token):
    switch_on_auth(github_client)

    jwt = github_request_token

#   set valid auth headers
    schemas = requests.get(URL, headers={'Authorization': 'Bearer ' + jwt})

#   test that user has access
    assert schemas.status_code == 200

    switch_off_auth(github_client)


@if_github
def test_github_auth_config_api_whitelist_users(github_client):

    github_client.create_githubconfig(allowedUsers=['ranchertest01',
                                                        'ranchertest02'])

#   test that these users were whitelisted
    r = github_client.list_githubconfig()

    users = r[0]['allowedUsers']

    assert len(users) == 2

    assert 'ranchertest01' in users
    assert 'ranchertest02' in users


@if_github
def test_github_auth_config_api_whitelist_orgs(github_client):

    github_client.create_githubconfig(allowedOrganizations=['rancherio'])

#   test that these users were whitelisted
    r = github_client.list_githubconfig()

    orgs = r[0]['allowedOrganizations']

    assert len(orgs) == 1

    assert 'rancherio' in orgs


@if_github
def test_github_add_whitelisted_user(github_client):
    switch_on_auth(github_client)

    #   set whitelisted orgs
    github_client.create_githubconfig(allowedUsers=['ranchertest01'])

    #   test that these users were whitelisted
    r = github_client.list_githubconfig()

    users = r[0]['allowedUsers']

    assert 'ranchertest01' in users

    rancherpass = os.getenv('API_AUTH_RANCHER_TEST_PASS', None)

    if rancherpass is None:
        assert False

    new_token = github_request_code('ranchertest01', rancherpass)

    assert new_token is not None

    switch_off_auth(github_client)


@if_github
def test_github_projects(github_client, cattle_url):
    user_client = from_env(url=cattle_url)
    switch_on_auth(github_client)

    #   set whitelisted orgs
    github_client.create_githubconfig(allowedUsers=['ranchertest01'])

    #   test that these users were whitelisted
    r = github_client.list_githubconfig()

    users = r[0]['allowedUsers']

    assert 'ranchertest01' in users

    rancherpass = os.getenv('API_AUTH_RANCHER_TEST_PASS', None)

    if rancherpass is None:
        assert False

    new_token = github_request_code('ranchertest01', rancherpass)
    new_token = github_request_token(new_token)
    user_client._auth = GithubAuth(new_token)
    try:
        user_client.create_project(externalIdType='project:github_user')
    except:
        pass

    projects = user_client.list_project()

    assert len(projects) == 1

    switch_off_auth(github_client)
