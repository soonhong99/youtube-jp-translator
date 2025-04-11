import React from 'react';
import UrlInput from '../components/UrlInput';
import '../styles/animations.css';

const Home = () => {
  return (
    <div className="relative w-full h-screen overflow-hidden">
      <video autoPlay loop muted className="absolute w-full h-full object-cover -z-10">
        <source src="/assets/bg-animation.mp4" type="video/mp4" />
      </video>
      <div className="flex flex-col items-center justify-center h-full text-white backdrop-blur-sm">
        <h1 className="text-5xl font-bold mb-6 animate-fadeIn">YouTube 일본어 STT & 번역</h1>
        <p className="mb-8 text-lg animate-fadeIn delay-200">일본어 유튜브 영상 자막을 실시간으로 변환하고 병렬 출력까지!</p>
        <UrlInput redirectOnSubmit />
      </div>
    </div>
  );
};

export default Home;