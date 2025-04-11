import React from 'react';
import { Link } from 'react-router-dom';

const Navbar = () => (
  <nav className="bg-white shadow-md py-4 px-8 flex justify-between items-center sticky top-0 z-50">
    <h1 className="text-xl font-bold text-blue-700">JP-KR YouTube Translator</h1>
    <div className="space-x-6">
      <Link to="/" className="hover:text-blue-500 font-medium">홈</Link>
      <Link to="/translate" className="hover:text-blue-500 font-medium">번역결과</Link>
    </div>
  </nav>
);

export default Navbar;