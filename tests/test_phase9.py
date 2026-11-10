"""Marketplace inventory, checkout and redemption checks for Phase 9."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('CHOREGREMLIN_DATA_DIR', tempfile.mkdtemp(prefix='cg-phase9-'))
os.environ.setdefault('SECRET_KEY', 'phase9-test-secret-key-not-for-production')

import db as db_module  # noqa: E402
import app as app_module  # noqa: E402


class MarketplacePersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        cls.parent_id = db_module.create_user(
            'Phase 9 Parent', None, None, role='parent', username='phase9_parent'
        )

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()

    def child(self, name):
        return db_module.create_user(name, None, None, role='child')

    def funded_child(self, name, amount=100):
        child_id = self.child(name)
        db_module.create_payment(
            child_id, amount, ptype='earning',
            description='Phase 9 test funding', auto_repay=False
        )
        return child_id

    def item(self, name='Movie night', price=25, stock=3, category='privilege', **kwargs):
        return db_module.create_marketplace_item(
            name, price, category, kwargs.pop('description', 'Test reward'),
            stock_quantity=stock, **kwargs
        )

    def test_migration_28_creates_marketplace_tables(self):
        db = db_module.get_db()
        version = db.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_version"
        ).fetchone()[0]
        self.assertGreaterEqual(version, 28)
        names = {
            row['name'] for row in db.execute(
                """SELECT name FROM sqlite_master WHERE type='table'
                   AND name IN ('marketplace_items', 'marketplace_orders')"""
            ).fetchall()
        }
        self.assertEqual(names, {'marketplace_items', 'marketplace_orders'})

    def test_inventory_item_crud_and_validation(self):
        item_id = self.item('Pizza night', 30, stock=5, category='privilege')
        item = db_module.get_marketplace_item(item_id)
        self.assertEqual(item['name'], 'Pizza night')
        self.assertEqual(item['category'], 'privilege')
        self.assertEqual(item['stock_quantity'], 5)

        updated = db_module.update_marketplace_item(
            item_id, 'Pizza and film night', 35, category='privilege',
            description='Two rewards in one', stock_quantity='', icon='bi-film'
        )
        self.assertEqual(updated['name'], 'Pizza and film night')
        self.assertEqual(updated['price'], 35)
        self.assertIsNone(updated['stock_quantity'])
        self.assertEqual(updated['icon'], 'bi-film')

        db_module.set_marketplace_item_active(item_id, False)
        self.assertEqual(db_module.get_marketplace_item(item_id)['is_active'], 0)
        self.assertNotIn(item_id, [row['id'] for row in db_module.get_marketplace_items(active_only=True)])

        with self.assertRaises(ValueError):
            db_module.create_marketplace_item('', 10)
        with self.assertRaises(ValueError):
            db_module.create_marketplace_item('Bad category', 10, category='food')
        with self.assertRaises(ValueError):
            db_module.create_marketplace_item('Bad price', 0)
        with self.assertRaises(ValueError):
            db_module.create_marketplace_item('Bad stock', 10, stock_quantity=-1)

    def test_checkout_validates_balance_and_reserves_stock(self):
        child_id = self.funded_child('Phase 9 Checkout Child', 20)
        item_id = self.item('Comic', 10, stock=2, category='item')
        order_id = db_module.create_marketplace_order(child_id, item_id, 2, 'Birthday')
        order = db_module.get_marketplace_order(order_id)
        self.assertEqual(order['status'], 'pending')
        self.assertEqual(order['quantity'], 2)
        self.assertEqual(order['total_amount'], 20)
        self.assertEqual(order['notes'], 'Birthday')
        self.assertEqual(db_module.get_balance(child_id), 0)
        self.assertEqual(db_module.get_marketplace_item(item_id)['stock_quantity'], 0)
        self.assertTrue(order['qr_token'])
        self.assertTrue(
            any(payment['type'] == 'marketplace_purchase' for payment in db_module.get_payments(child_id))
        )

        with self.assertRaises(ValueError):
            db_module.create_marketplace_order(child_id, item_id, 1)

        poor_child = self.funded_child('Phase 9 Poor Child', 5)
        expensive_item = self.item('Expensive toy', 30, stock=1)
        with self.assertRaises(ValueError):
            db_module.create_marketplace_order(poor_child, expensive_item, 1)
        self.assertEqual(db_module.get_balance(poor_child), 5)
        self.assertEqual(db_module.get_marketplace_item(expensive_item)['stock_quantity'], 1)

    def test_inactive_and_invalid_quantity_cannot_be_ordered(self):
        child_id = self.funded_child('Phase 9 Invalid Order Child', 100)
        item_id = self.item('Hidden item', 10, stock=1)
        db_module.set_marketplace_item_active(item_id, False)
        with self.assertRaises(ValueError):
            db_module.create_marketplace_order(child_id, item_id, 1)

        active_item = self.item('Quantity item', 10, stock=10)
        with self.assertRaises(ValueError):
            db_module.create_marketplace_order(child_id, active_item, 0)
        with self.assertRaises(ValueError):
            db_module.create_marketplace_order(child_id, active_item, 11)

    def test_reject_refunds_balance_and_restores_stock(self):
        child_id = self.funded_child('Phase 9 Reject Child', 40)
        item_id = self.item('Reject item', 15, stock=2)
        order_id = db_module.create_marketplace_order(child_id, item_id, 1)
        self.assertEqual(db_module.get_balance(child_id), 25)
        self.assertEqual(db_module.get_marketplace_item(item_id)['stock_quantity'], 1)

        rejected = db_module.reject_marketplace_order(order_id, self.parent_id, 'Not today')
        self.assertEqual(rejected['status'], 'rejected')
        self.assertEqual(rejected['rejection_reason'], 'Not today')
        self.assertEqual(db_module.get_balance(child_id), 40)
        self.assertEqual(db_module.get_marketplace_item(item_id)['stock_quantity'], 2)
        self.assertTrue(
            any(payment['type'] == 'marketplace_refund' for payment in db_module.get_payments(child_id))
        )

    def test_cancel_refunds_balance_and_restores_stock(self):
        child_id = self.funded_child('Phase 9 Cancel Child', 40)
        item_id = self.item('Cancel item', 20, stock=2)
        order_id = db_module.create_marketplace_order(child_id, item_id, 1)
        cancelled = db_module.cancel_marketplace_order(order_id, child_id)
        self.assertEqual(cancelled['status'], 'cancelled')
        self.assertEqual(db_module.get_balance(child_id), 40)
        self.assertEqual(db_module.get_marketplace_item(item_id)['stock_quantity'], 2)

        with self.assertRaises(ValueError):
            db_module.cancel_marketplace_order(order_id, child_id)

    def test_approve_then_fulfill_completes_order(self):
        child_id = self.funded_child('Phase 9 Fulfill Child', 40)
        item_id = self.item('Fulfill item', 20, stock=2)
        order_id = db_module.create_marketplace_order(child_id, item_id, 1)

        approved = db_module.approve_marketplace_order(order_id, self.parent_id)
        self.assertEqual(approved['status'], 'approved')
        self.assertEqual(approved['approved_by'], self.parent_id)
        self.assertIsNotNone(approved['approved_at'])

        fulfilled = db_module.fulfill_marketplace_order(order_id, self.parent_id)
        self.assertEqual(fulfilled['status'], 'fulfilled')
        self.assertEqual(fulfilled['fulfilled_by'], self.parent_id)
        self.assertIsNotNone(fulfilled['fulfilled_at'])
        self.assertEqual(db_module.get_marketplace_item(item_id)['stock_quantity'], 1)
        self.assertEqual(db_module.get_balance(child_id), 20)

    def test_fulfill_can_approve_a_pending_order(self):
        child_id = self.funded_child('Phase 9 Direct Fulfill Child', 20)
        item_id = self.item('Direct fulfill item', 10, stock=1)
        order_id = db_module.create_marketplace_order(child_id, item_id, 1)
        fulfilled = db_module.fulfill_marketplace_order(order_id, self.parent_id)
        self.assertEqual(fulfilled['status'], 'fulfilled')
        self.assertEqual(fulfilled['approved_by'], self.parent_id)

    def test_item_without_approval_is_ready_immediately(self):
        child_id = self.funded_child('Phase 9 Auto Approve Child', 20)
        item_id = db_module.create_marketplace_item(
            'Auto reward', 10, 'item', stock_quantity=1, requires_approval=0
        )
        order_id = db_module.create_marketplace_order(child_id, item_id, 1)
        order = db_module.get_marketplace_order(order_id)
        self.assertEqual(order['status'], 'approved')
        self.assertIsNotNone(order['approved_at'])
        self.assertEqual(db_module.get_balance(child_id), 10)

    def test_unlimited_stock_does_not_decrement(self):
        child_id = self.funded_child('Phase 9 Unlimited Child', 50)
        item_id = self.item('Unlimited item', 10, stock=None)
        db_module.create_marketplace_order(child_id, item_id, 2)
        self.assertIsNone(db_module.get_marketplace_item(item_id)['stock_quantity'])
        db_module.create_marketplace_order(child_id, item_id, 3)
        self.assertIsNone(db_module.get_marketplace_item(item_id)['stock_quantity'])

    def test_qr_data_uri_is_generated(self):
        data_uri = app_module.marketplace_qr_data_uri('phase9-token')
        self.assertTrue(data_uri.startswith('data:image/png;base64,'))
        self.assertGreater(len(data_uri), 100)


class MarketplaceRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        if not db_module.is_setup_complete():
            db_module.create_user('Phase 9 Admin', None, 'phase9-test-password',
                                  role='admin', username='phase9_admin')
        cls.parent_id = db_module.create_user(
            'Phase 9 Route Parent', None, None, role='parent', username='phase9_route_parent'
        )
        cls.previous_csrf = app_module.app.config.get('WTF_CSRF_ENABLED', True)
        app_module.app.config['WTF_CSRF_ENABLED'] = False

    @classmethod
    def tearDownClass(cls):
        app_module.app.config['WTF_CSRF_ENABLED'] = cls.previous_csrf
        cls.ctx.pop()

    def setUp(self):
        self.client = app_module.app.test_client()
        with self.client.session_transaction() as sess:
            sess.clear()

    def login_parent(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.parent_id

    def login_child(self, child_id):
        with self.client.session_transaction() as sess:
            sess['kiosk_child_id'] = child_id

    def funded_child(self, name, amount=100):
        child_id = db_module.create_user(name, None, None, role='child')
        db_module.create_payment(
            child_id, amount, ptype='earning',
            description='Phase 9 route funding', auto_repay=False
        )
        return child_id

    def test_parent_marketplace_page_and_inventory_routes(self):
        self.login_parent()
        response = self.client.get('/marketplace')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Chore Gremlin Marketplace', response.data)
        self.assertIn(b'Inventory', response.data)

        response = self.client.post('/marketplace/items/add', data={
            'name': 'Phase 9 Route Item',
            'description': 'Added by route test',
            'category': 'screen_time',
            'price': '15',
            'stock_quantity': '4',
            'icon': 'bi-display',
            'color': '#10b981',
            'requires_approval': '1',
            'sort_order': '2',
        })
        self.assertEqual(response.status_code, 302)
        items = db_module.get_marketplace_items()
        item = next(row for row in items if row['name'] == 'Phase 9 Route Item')
        self.assertEqual(item['category'], 'screen_time')
        self.assertEqual(item['stock_quantity'], 4)

        response = self.client.post(f'/marketplace/items/{item["id"]}/update', data={
            'name': 'Phase 9 Route Item Updated',
            'description': 'Updated',
            'category': 'item',
            'price': '12.5',
            'stock_quantity': '',
            'icon': 'bi-bag-fill',
            'color': '#10b981',
            'requires_approval': '1',
            'sort_order': '0',
        })
        self.assertEqual(response.status_code, 302)
        updated = db_module.get_marketplace_item(item['id'])
        self.assertEqual(updated['name'], 'Phase 9 Route Item Updated')
        self.assertIsNone(updated['stock_quantity'])

        response = self.client.post(f'/marketplace/items/{item["id"]}/toggle')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db_module.get_marketplace_item(item['id'])['is_active'], 0)

    def test_parent_order_approve_fulfill_and_verify_routes(self):
        child_id = self.funded_child('Phase 9 Route Fulfill Child', 30)
        item_id = db_module.create_marketplace_item(
            'Phase 9 Route Fulfill Item', 10, 'item', stock_quantity=2
        )
        order_id = db_module.create_marketplace_order(child_id, item_id, 1)
        order = db_module.get_marketplace_order(order_id)
        self.login_parent()

        response = self.client.get(f'/marketplace/verify/{order["qr_token"]}')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Verify Redemption', response.data)
        self.assertIn(b'Phase 9 Route Fulfill Item', response.data)

        response = self.client.post('/marketplace/verify', data={'token': order['qr_token']})
        self.assertEqual(response.status_code, 200)

        response = self.client.post(f'/marketplace/orders/{order_id}/approve')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db_module.get_marketplace_order(order_id)['status'], 'approved')

        response = self.client.post(f'/marketplace/orders/{order_id}/fulfill')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db_module.get_marketplace_order(order_id)['status'], 'fulfilled')

    def test_parent_reject_route_refunds(self):
        child_id = self.funded_child('Phase 9 Route Reject Child', 30)
        item_id = db_module.create_marketplace_item(
            'Phase 9 Route Reject Item', 10, 'item', stock_quantity=2
        )
        order_id = db_module.create_marketplace_order(child_id, item_id, 1)
        self.login_parent()
        response = self.client.post(f'/marketplace/orders/{order_id}/reject', data={
            'reason': 'Try again later'
        })
        self.assertEqual(response.status_code, 302)
        order = db_module.get_marketplace_order(order_id)
        self.assertEqual(order['status'], 'rejected')
        self.assertEqual(order['rejection_reason'], 'Try again later')
        self.assertEqual(db_module.get_balance(child_id), 30)
        self.assertEqual(db_module.get_marketplace_item(item_id)['stock_quantity'], 2)

    def test_kiosk_shop_page_buy_and_cancel(self):
        child_id = self.funded_child('Phase 9 Kiosk Child', 30)
        item_id = db_module.create_marketplace_item(
            'Phase 9 Kiosk Item', 10, 'item', stock_quantity=2
        )
        self.login_child(child_id)

        response = self.client.get('/kiosk/shop')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Phase 9 Kiosk Child's Shop", response.data)
        self.assertIn(b'Phase 9 Kiosk Item', response.data)

        response = self.client.post(f'/kiosk/shop/buy/{item_id}', data={'quantity': '1'})
        self.assertEqual(response.status_code, 302)
        orders = db_module.get_marketplace_orders(child_id)
        self.assertEqual(len(orders), 1)
        order_id = orders[0]['id']
        self.assertEqual(orders[0]['status'], 'pending')
        self.assertEqual(db_module.get_balance(child_id), 20)

        response = self.client.get('/kiosk/shop')
        self.assertIn(b'Show QR', response.data)

        response = self.client.post(f'/kiosk/shop/orders/{order_id}/cancel')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db_module.get_marketplace_order(order_id)['status'], 'cancelled')
        self.assertEqual(db_module.get_balance(child_id), 30)
        self.assertEqual(db_module.get_marketplace_item(item_id)['stock_quantity'], 2)

    def test_marketplace_routes_have_access_rules(self):
        self.assertEqual(app_module.ROUTE_ACCESS.get('marketplace'), 'staff')
        self.assertEqual(app_module.ROUTE_ACCESS.get('marketplace_item_add'), 'staff')
        self.assertEqual(app_module.ROUTE_ACCESS.get('marketplace_item_update'), 'staff')
        self.assertEqual(app_module.ROUTE_ACCESS.get('marketplace_item_toggle'), 'staff')
        self.assertEqual(app_module.ROUTE_ACCESS.get('marketplace_order_approve'), 'staff')
        self.assertEqual(app_module.ROUTE_ACCESS.get('marketplace_order_reject'), 'staff')
        self.assertEqual(app_module.ROUTE_ACCESS.get('marketplace_order_fulfill'), 'staff')
        self.assertEqual(app_module.ROUTE_ACCESS.get('marketplace_verify'), 'staff')
        self.assertEqual(app_module.ROUTE_ACCESS.get('kiosk_shop'), 'kiosk')
        self.assertEqual(app_module.ROUTE_ACCESS.get('kiosk_shop_buy'), 'kiosk')
        self.assertEqual(app_module.ROUTE_ACCESS.get('kiosk_shop_cancel'), 'kiosk')


if __name__ == '__main__':
    unittest.main()
