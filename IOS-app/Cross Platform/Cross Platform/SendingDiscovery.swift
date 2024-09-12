import Foundation
import Network
import Combine

class SendingDiscovery: ObservableObject {
    @Published var devices: [String] = []
    private var udpListener: NWListener?
    private let udpQueue = DispatchQueue(label: "UDPQueue")
    private let discoveryPort: NWEndpoint.Port = 12345  // Port for sending DISCOVER messages
    private let listeningPort: NWEndpoint.Port = 12346  // Port for listening to RECEIVER messages
    private var isListening = false
    private var discoveryTimer: Timer?

    func startContinuousDiscovery() {
        if !isListening {
            setupUDPListener()
            isListening = true
        }

        discoveryTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            self?.sendDiscoverMessage()
        }
    }

    func stopContinuousDiscovery() {
        discoveryTimer?.invalidate()
        discoveryTimer = nil
        isListening = false
        stopUDPListener()
    }

    func setupUDPListener() {
        do {
            udpListener = try NWListener(using: .udp, on: listeningPort)  // Listen on port 12346
            udpListener?.newConnectionHandler = { [weak self] connection in
                self?.handleNewUDPConnection(connection)
            }
            udpListener?.start(queue: udpQueue)
            print("UDP Listener started on port \(listeningPort.rawValue)")
        } catch {
            print("Failed to create UDP listener: \(error)")
        }
    }

    func stopUDPListener() {
        udpListener?.cancel()
        udpListener = nil
        print("UDP Listener stopped")
    }

    func sendDiscoverMessage() {
        print("Sending DISCOVER message")
        let broadcastAddress = "192.168.29.255"
        let connection = NWConnection(host: NWEndpoint.Host(broadcastAddress), port: discoveryPort, using: .udp)  // Send on port 12345
        connection.start(queue: udpQueue)
        let discoverMessage = "DISCOVER".data(using: .utf8)
        
        connection.send(content: discoverMessage, completion: .contentProcessed { error in
            if let error = error {
                print("Failed to send DISCOVER message: \(error.localizedDescription)")
                connection.cancel()
            } else {
                print("DISCOVER message sent successfully")
                connection.cancel()
            }
        })
    }

    func connectToDevice(_ device: String) {
        // Add your connection logic here
        print("Connecting to device: \(device)")
    }

    private func handleNewUDPConnection(_ connection: NWConnection) {
        connection.start(queue: udpQueue)
        connection.receiveMessage { [weak self] data, _, _, error in
            if let error = error {
                print("Error receiving message: \(error.localizedDescription)")
                return
            }
            guard let data = data, let message = String(data: data, encoding: .utf8) else { return }
            print("Received message: \(message)")

            if message.hasPrefix("RECEIVER:") {
                let deviceName = message.replacingOccurrences(of: "RECEIVER:", with: "")
                DispatchQueue.main.async {
                    if !self!.devices.contains(deviceName) {
                        self!.devices.append(deviceName)
                        print("Discovered device: \(deviceName)")
                    }
                }
            }
        }
    }
}
