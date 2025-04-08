import React from 'react';
import { Link } from 'react-router-dom';

export default function Navbar() {
  return (
    <nav style={styles.navbar}>
      <Link style={styles.link} to="/">홈페이지</Link>
      <Link style={styles.link} to="/translate">번역결과</Link>
      <Link style={styles.link} to="/download">다운로드</Link>
      <Link style={styles.link} to="/about">서비스 소개</Link>
    </nav>
  );
}

const styles = {
  navbar: {
    display: 'flex',
    justifyContent: 'center',
    gap: '20px',
    padding: '15px',
    backgroundColor: '#007bff',
    marginBottom: '20px'
  },
  link: {
    color: 'white',
    textDecoration: 'none',
    fontSize: '16px',
    fontWeight: 'bold'
  }
};
