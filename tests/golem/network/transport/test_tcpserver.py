import unittest
from unittest.mock import Mock

from golem.network.transport.tcpnetwork import SocketAddress

from golem.network.transport.tcpserver import (
    TCPServer, PendingConnectionsServer, PendingConnection, PenConnStatus)


class ConfigDescriptor(object):
    def __init__(self, start_port, end_port):
        self.start_port = start_port
        self.end_port = end_port


class Network(object):
    def __init__(self):
        self.stop_listening_called = False
        self.listen_called = False
        self.connected = False

    def listen(self, _, listen_id=None):
        self.listen_called = True

    def stop_listening(self, _):
        self.stop_listening_called = True

    def connect(self, connect_info):
        self.connected = True


class TestTCPServer(unittest.TestCase):

    def __test_change_scenario(self, server, port, start_port, end_port, stop_state, listen_state):
        server.network = Network()
        server.cur_port = port
        server.change_config(ConfigDescriptor(start_port, end_port))
        self.assertEqual(server.network.stop_listening_called, stop_state)
        self.assertEqual(server.network.listen_called, listen_state)

    def test_change_config(self):
        server = TCPServer(None, Network())
        self.assertEqual(server.cur_port, 0)
        self.assertFalse(server.network.stop_listening_called)
        server.change_config(ConfigDescriptor(10, 20))
        self.assertFalse(server.network.stop_listening_called)
        self.assertTrue(server.network.listen_called)

        self.__test_change_scenario(server, 10, 10, 20, False, False)
        self.__test_change_scenario(server, 15, 10, 20, False, False)
        self.__test_change_scenario(server, 20, 10, 20, False, False)
        self.__test_change_scenario(server, 21, 10, 20, True, True)
        self.__test_change_scenario(server, 30, 10, 20, True, True)
        self.__test_change_scenario(server, 9, 10, 20, True, True)
        self.__test_change_scenario(server, 10, 10, 10, False, False)
        self.__test_change_scenario(server, 11, 10, 10, True, True)
        self.__test_change_scenario(server, 0, 10, 10, False, True)


class TestPendingConnectionServer(unittest.TestCase):
    def setUp(self):
        self.key_id = "d0d1d2"
        self.port = 1234

        node_info = Mock()
        node_info.key = 'deadbeef'
        node_info.prv_addresses = ["10.10.10.2"]
        node_info.pub_addr = "10.10.10.1"
        node_info.pub_port = self.port
        node_info.prv_port = self.port - 1

        self.node_info = node_info

    def test_get_socket_addresses(self):
        server = PendingConnectionsServer(None, Network())

        node = self.node_info
        res = server.get_socket_addresses(node,
                                          prv_port=node.prv_port,
                                          pub_port=node.pub_port)
        self.assertEqual(res, [
            SocketAddress(self.node_info.pub_addr, self.node_info.pub_port),
            SocketAddress(self.node_info.prv_addresses[0],
                          self.node_info.prv_port)
        ])
        node.pub_addr = "10.10.10.10"
        res = server.get_socket_addresses(node,
                                          prv_port=node.prv_port,
                                          pub_port=node.pub_port)
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0].address, node.pub_addr)
        self.assertEqual(res[0].port, node.pub_port)
        node.pub_port = 1023
        res = server.get_socket_addresses(node,
                                          prv_port=node.prv_port,
                                          pub_port=node.pub_port)
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0].address, node.pub_addr)
        self.assertEqual(res[0].port, 1023)

        node.prv_addresses = ["10.10.10.1", "10.10.10.2",
                              "10.10.10.3", "10.10.10.4"]

        res = server.get_socket_addresses(node,
                                          prv_port=node.prv_port,
                                          pub_port=node.pub_port)
        self.assertEqual(len(res), 5)
        self.assertEqual(res[4].address, node.prv_addresses[-1])
        self.assertEqual(res[4].port, 1233)
        for i in range(4):
            self.assertEqual(res[i + 1].address, node.prv_addresses[i])
            self.assertEqual(res[i + 1].port, node.prv_port)
        node.pub_addr = None
        res = server.get_socket_addresses(node,
                                          prv_port=node.prv_port,
                                          pub_port=node.pub_port)
        self.assertEqual(len(res), 4)
        for i in range(4):
            self.assertEqual(res[i].address, node.prv_addresses[i])
            self.assertEqual(res[i].port, node.prv_port)

    def test_address_accessible(self):
        config = Mock()
        config.use_ipv6 = False

        server = PendingConnectionsServer(config, Mock())

        assert not server._is_address_accessible(None)

        sockv4 = SocketAddress('8.8.8.8', 40100)
        sockv6 = SocketAddress('2001:0db8:85a3:0000:0000:8a2e:abcd:efea', 40100)

        assert server._is_address_accessible(sockv4)
        assert not server._is_address_accessible(sockv6)

        server.use_ipv6 = True

        assert server._is_address_accessible(sockv4)
        assert server._is_address_accessible(sockv6)

    def test_pending_conn(self):
        network = Network()
        server = PendingConnectionsServer(None, network)
        req_type = 0
        final_failure_called = [False]

        def final_failure(*args, **kwargs):
            final_failure_called[0] = True

        server.resume()
        server.conn_established_for_type[req_type] = lambda x: x
        server.conn_failure_for_type[req_type] = server.final_conn_failure
        server.conn_final_failure_for_type[req_type] = final_failure
        server._is_address_accessible = Mock(return_value=True)

        server._add_pending_request(
            req_type,
            self.node_info,
            prv_port=self.node_info.prv_port,
            pub_port=self.node_info.pub_port,
            args={}
        )
        assert len(server.pending_connections) == 1
        pending_conn = next(iter(list(server.pending_connections.values())))

        final_failure_called[0] = False
        server.final_conn_failure(pending_conn.id)
        assert final_failure_called[0]

        server.verified_conn(pending_conn.id)
        assert len(server.pending_connections) == 0

        final_failure_called[0] = False
        server.final_conn_failure(pending_conn.id)
        assert not final_failure_called[0]

        server._add_pending_request(
            req_type,
            self.node_info,
            prv_port=self.node_info.prv_port,
            pub_port=self.node_info.pub_port,
            args={}
        )
        pending_conn = next(iter(list(server.pending_connections.values())))
        server._mark_connected(pending_conn.id, "10.10.10.1", self.port)
        assert pending_conn.status == PenConnStatus.Connected
        assert SocketAddress("10.10.10.1", self.port) == pending_conn.socket_addresses[0]

    def test_sync_pending(self):
        network = Network()
        server = PendingConnectionsServer(None, network)
        req_type = 0
        final_failure_called = [False]

        node_info = Mock(
            key='1234',
            prv_addresses=["1.2.3.4"],
            pub_addr="1.2.3.4",
            pub_port=self.port
        )

        def final_failure(*args, **kwargs):
            final_failure_called[0] = True

        server.resume()
        server.conn_established_for_type[req_type] = lambda x: x
        server.conn_failure_for_type[req_type] = server.final_conn_failure
        server.conn_final_failure_for_type[req_type] = final_failure
        server._is_address_accessible = Mock(return_value=True)

        server._add_pending_request(
            req_type,
            node_info,
            prv_port=node_info.prv_port,
            pub_port=node_info.pub_port,
            args={}
        )
        assert len(server.pending_connections) == 1

        server._sync_pending()
        assert network.connected

        network.connected = False
        server.pending_connections = {}

        server._add_pending_request(
            req_type,
            self.node_info,
            prv_port=self.node_info.prv_port,
            pub_port=self.node_info.pub_port,
            args={}
        )
        assert len(server.pending_connections) == 1
        pending_conn = next(iter(list(server.pending_connections.values())))
        pending_conn.socket_addresses = []

        server._sync_pending()
        assert not network.connected
        assert final_failure_called[0]


class TestPendingConnection(unittest.TestCase):
    def test_init(self):
        pc = PendingConnection(1, "10.10.10.10")
        self.assertIsInstance(pc, PendingConnection)
