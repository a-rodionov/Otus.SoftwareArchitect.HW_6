import os
import json
import requests

from flask import Flask, request
from flask_api import status
from flask_wtf import FlaskForm
from wtforms import IntegerField
from wtforms.validators import DataRequired
from sqlalchemy import create_engine

class CreateOrderForm(FlaskForm):
    userId = IntegerField("userId: ", validators=[DataRequired()])
    price = IntegerField("price: ", validators=[DataRequired()])

app = Flask(__name__)

ERROR_UNEXPECTED = 1
ERROR_INPUT_DATA = 2
ERROR_OBJECT_NOT_FOUND = 3

SUCCESSFUL_EMAIL_TITLE = 'Order is paid'
FAILURE_EMAIL_TITLE = 'Not enough money'

config = {
    'DATABASE_URI': os.environ.get('DATABASE_URI', ''),
    'HOSTNAME': os.environ['HOSTNAME'],
    'APP_NAME': os.environ.get('APP_NAME', 'no name'),
    'BILLING_SERVICE_URL': os.environ['BILLING_SERVICE_URL'],
    'NOTIFICATION_SERVICE_URL': os.environ['NOTIFICATION_SERVICE_URL']
}

@app.route("/")
def hello():
    return 'Application \'' + config['APP_NAME'] + '\' from ' + config['HOSTNAME'] + '!'

@app.route("/health")
def health():
    return '{"status": "ok"}'

@app.route("/config")
def configuration():
    return json.dumps(config)

@app.route('/orders', methods=['POST'])
def order_create():
    try:
        createOrderForm = CreateOrderForm(meta={'csrf': False})
        if createOrderForm.validate():

            result = requests.get(config['BILLING_SERVICE_URL'] + '/billing/user/' + str(createOrderForm.userId.data))
            if (status.HTTP_500_INTERNAL_SERVER_ERROR == result.status_code or
                status.HTTP_400_BAD_REQUEST == result.status_code):
                return json.dumps({'code': ERROR_UNEXPECTED, 'message': 'Billing service getting user info error: ' + result.json().get('message')}), result.status_code
            elif status.HTTP_200_OK != result.status_code:
                return '', result.status_code
            userInfo = result.json()

            engine = create_engine(config['DATABASE_URI'], echo=True)
            with engine.connect() as connection:
                result = connection.execute('''insert into orders (userId, price) values(%s, %s) returning id''',
                                            (createOrderForm.userId.data,
                                             createOrderForm.price.data))
                orderId = result.scalar()
                if orderId is None:
                    return json.dumps({'code': ERROR_UNEXPECTED, 'message': 'Failed to create order in DB'}), status.HTTP_500_INTERNAL_SERVER_ERROR

            result = requests.post(config['BILLING_SERVICE_URL'] + '/billing/withdraw/' + str(createOrderForm.userId.data), json={'amount': createOrderForm.price.data})
            if status.HTTP_200_OK == result.status_code:
                with engine.connect() as connection:
                    result = connection.execute('''update orders set status = 1 where id = %s returning id''', orderId)
                    orderId = result.scalar()
                    if orderId is None:
                        return json.dumps({'code': ERROR_UNEXPECTED, 'message': 'Failed to update order status in DB'}), status.HTTP_500_INTERNAL_SERVER_ERROR
                requests.post(config['NOTIFICATION_SERVICE_URL'] + '/notification/email/' + str(createOrderForm.userId.data),
                              json={'email': userInfo.get('email'), 'title': SUCCESSFUL_EMAIL_TITLE, 'message': 'Success'})
                return json.dumps({'orderId': orderId}), status.HTTP_201_CREATED

            elif status.HTTP_412_PRECONDITION_FAILED == result.status_code:
                requests.post(config['NOTIFICATION_SERVICE_URL'] + '/notification/email/' + str(createOrderForm.userId.data),
                              json={'email': userInfo.get('email'), 'title': FAILURE_EMAIL_TITLE, 'message': 'Failure'})
                return json.dumps({'orderId': orderId}), status.HTTP_412_PRECONDITION_FAILED

            else:
                return json.dumps({'code': ERROR_UNEXPECTED, 'message': 'Billing service withdraw error: ' + result.json().get('message')}), result.status_code
        else:
            return json.dumps({'code': ERROR_INPUT_DATA, 'message': str(createOrderForm.errors)}), status.HTTP_400_BAD_REQUEST
    except Exception as exc:
        return json.dumps({'code': ERROR_UNEXPECTED, 'message': str(exc)}), status.HTTP_500_INTERNAL_SERVER_ERROR

@app.route('/orders/<int:orderId>', methods=['GET'])
def order_get(orderId):
    try:
        engine = create_engine(config['DATABASE_URI'], echo=True)
        rows = []
        with engine.connect() as connection:
            result = connection.execute('''select * from orders where id=%s''', userId)
            row = result.first()
            if row is None:
                return '', status.HTTP_404_NOT_FOUND
            else:
                return json.dumps(dict(row.items())), status.HTTP_200_OK
    except Exception as exc:
        return json.dumps({'code': ERROR_UNEXPECTED, 'message': str(exc)}), status.HTTP_500_INTERNAL_SERVER_ERROR

if __name__ == "__main__":
    app.run(host='0.0.0.0',port='8000')
