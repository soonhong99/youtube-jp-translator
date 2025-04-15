import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Home from './pages/Home';
import TranslateResult from './pages/TranslateResult';
import Navbar from './components/Navbar';
import './styles/globals.css';

function App() {
  return (
    <Router>
      <Navbar />
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/translate" element={<TranslateResult />} />
      </Routes>
    </Router>
  );
}

export default App;


