import logo from './logo.svg';
import './App.css';

import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Home from './components/Home';
import TranslateResult from './components/TranslateResult';
import Download from './components/Download';
import About from './components/About';
import Navbar from './components/Navbar';


function App() {
  return (
    <Router>
      <Navbar />
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/translate" element={<TranslateResult />} />
        <Route path="/download" element={<Download />} />
        <Route path="/about" element={<About />} />
      </Routes>
    </Router>
  );
}

export default App;
