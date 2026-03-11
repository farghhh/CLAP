// SERVER 1

//socket.io
const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const { createAdapter } = require('@socket.io/redis-adapter');
const { createClient } = require('redis');

const PORT        = 3001;
const SERVER_NAME = 'Server-1';

const app    = express();
const server = http.createServer(app);

app.use(express.static('public'));

const io = new Server(server);

// REDIS ADAPTER

async function setupRedisAdapter() {
  try {
    const pubClient = createClient({ url: 'redis://localhost:6379' });
    const subClient = pubClient.duplicate();

    pubClient.on('error', (err) => console.error(`[${SERVER_NAME}] Redis Pub Error:`, err));
    subClient.on('error', (err) => console.error(`[${SERVER_NAME}] Redis Sub Error:`, err));

    await pubClient.connect();
    await subClient.connect();

    io.adapter(createAdapter(pubClient, subClient));
    console.log(`[${SERVER_NAME}] Redis adapter connected successfully`);
  } catch (error) {
    console.error(`[${SERVER_NAME}] Redis connection failed:`, error.message);
    console.log(`[${SERVER_NAME}] Server will run without cross-server communication`);
  }
}

// SOCKET.IO

io.on('connection', (socket) => {
  console.log(`[${SERVER_NAME}] New client connected: ${socket.id}`);

  socket.data.username   = 'Anonymous';
  socket.data.department = '';

  broadcastUserList();

  //SET USERNAME + DEPARTMENT
  socket.on('set username', (data) => {
    if (typeof data === 'string') {
      socket.data.username = data;
    } else {
      socket.data.username   = data.username   || 'Anonymous';
      socket.data.department = data.department || '';
    }
    console.log(`[${SERVER_NAME}] User identified: ${socket.data.username} [${socket.data.department}]`);
    broadcastUserList();
  });

  // CHAT MESSAGE
  socket.on('chat message', (data) => {
    console.log(`[${SERVER_NAME}] ${data.username} [${data.department}]: ${data.message}`);

    io.emit('chat message', {
      username:   data.username,
      department: data.department || '',
      message:    data.message,
      timestamp:  data.timestamp
    });
  });

  // DISCONNECT
  socket.on('disconnect', () => {
    console.log(`[${SERVER_NAME}] Client disconnected: ${socket.data.username}`);
    broadcastUserList();
  });
});

// HELPERS

async function broadcastUserList() {
  try {
    const sockets   = await io.fetchSockets();
    const userArray = sockets.map(s => ({
      id:         s.id,
      username:   s.data.username   || 'Anonymous',
      department: s.data.department || ''
    }));

    io.emit('user list', userArray);
    console.log(`[${SERVER_NAME}] User list updated. Total: ${userArray.length}`);
  } catch (error) {
    console.error(`[${SERVER_NAME}] Error broadcasting user list:`, error);
  }
}

// START

async function startServer() {
  await setupRedisAdapter();
  server.listen(PORT, () => {
    console.log(`\n${'='.repeat(50)}`);
    console.log(`[${SERVER_NAME}] Server running on http://localhost:${PORT}`);
    console.log(`[${SERVER_NAME}] Ready to accept WebSocket connections`);
    console.log(`${'='.repeat(50)}\n`);
  });
}

startServer();