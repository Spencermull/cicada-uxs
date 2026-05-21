#pragma once
#include <ardupilotmega/mavlink.h>
#include <winsock2.h> // windows specific networking libs
#include <ws2tcpip.h>
#include <stdexcept>
#pragma comment(lib, "ws2_32.lib")



class UDPOPEN  // UDP socket opener class
{
    private:
    SOCKET sock;
    sockaddr_in localAddr;
    uint8_t buffer[512];
    mavlink_message_t msg;
    mavlink_status_t status;
    WSADATA wsaData;
public:
    UDPOPEN(){   
        WSAStartup(  // init winsock
           MAKEWORD(2, 2), &wsaData     
        );

         int result = WSAStartup(MAKEWORD(2,2), &wsaData); // check if process is up
        if(result != 0){
            throw std::runtime_error("WSAStartup Failed");
        }

        sock = ::socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP); // define the win socket for udp
        if(sock == INVALID_SOCKET){
            throw std::runtime_error("socket failed");
        }
    }
    

    void receive() const{};

    ~UDPOPEN(){

    }
    
};
