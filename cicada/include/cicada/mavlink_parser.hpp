#pragma once
#include <ardupilotmega/mavlink.h>
#include <winsock2.h> // windows specific networking libs
#include <ws2tcpip.h>
#include <stdexcept>
#pragma comment(lib, "ws2_32.lib") // TODO migrate to fit with gcc toolchain



class UdpSocket  // UDP socket opener class
{
    private:
    SOCKET sock;
    sockaddr_in localAddr;
    uint8_t buffer[2048]; // update to fit mavsdk frame output
    mavlink_message_t msg;
    mavlink_status_t status;
    WSADATA wsaData;
public:
    UdpSocket(){   
    
        int result = WSAStartup(MAKEWORD(2,2), &wsaData); // check if process is up
        if(result != 0){
            throw std::runtime_error("WSAStartup Failed");
        }

        sock = ::socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP); // define the win socket for udp
        if(sock == INVALID_SOCKET){
            throw std::runtime_error("socket failed");
        }
    }
    

    void receive() {
        
    };
     // destruct socket 
    ~UdpSocket(){
        WSACleanup();
        closesocket(sock);
    }
    
};
