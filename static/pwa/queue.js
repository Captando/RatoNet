'use strict';

class GPSQueue {
  constructor(owner) {
    this.owner = owner;
    this.database = new Promise((resolve, reject) => {
      const request = indexedDB.open('ratonet-gps', 1);
      request.onupgradeneeded = () => {
        const store = request.result.createObjectStore('points', { keyPath: 'id', autoIncrement: true });
        store.createIndex('owner', 'owner');
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async transaction(mode, operation) {
    const db = await this.database;
    return new Promise((resolve, reject) => {
      const tx = db.transaction('points', mode);
      let result;
      operation(tx.objectStore('points'), value => { result = value; });
      tx.oncomplete = () => resolve(result);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error || new Error('Fila GPS indisponível'));
    });
  }

  async add(data) {
    return this.transaction('readwrite', store => {
      store.add({ owner: this.owner, data });
      const request = store.index('owner').getAllKeys(this.owner);
      request.onsuccess = () => {
        request.result.slice(0, Math.max(0, request.result.length - 1000)).forEach(id => store.delete(id));
      };
    });
  }

  async list() {
    return this.transaction('readonly', (store, done) => {
      const request = store.index('owner').getAll(this.owner);
      request.onsuccess = () => done(request.result);
    });
  }

  async remove(id) {
    return this.transaction('readwrite', store => { store.delete(id); });
  }

  async clear() {
    return this.transaction('readwrite', store => {
      const request = store.index('owner').getAllKeys(this.owner);
      request.onsuccess = () => request.result.forEach(id => store.delete(id));
    });
  }
}

window.GPSQueue = GPSQueue;
