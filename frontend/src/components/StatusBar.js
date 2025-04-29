// // import React from 'react';

// // function StatusBar({ status, progress, error }) {
// //   return (
// //     <div className="bg-gray-100 p-4 mt-4 rounded-md shadow-inner">
// //       <h3 className="text-lg font-semibold mb-2">진행 상태</h3>
// //       <p className="text-gray-800">{status}</p>
// //       {progress !== null && (
// //         <div className="w-full bg-gray-300 rounded-full h-4 mt-3">
// //           <div
// //             className="bg-blue-600 h-4 text-xs text-white text-center rounded-full transition-all duration-300"
// //             style={{ width: `${progress}%` }}
// //           >
// //             {progress}%
// //           </div>
// //         </div>
// //       )}
// //       {error && <p className="text-red-600 mt-2">오류: {error}</p>}
// //     </div>
// //   );
// // }

// // export default StatusBar;

// // components/StatusBar.js
// import React from 'react';

// function StatusBar({ status, progress, error }) {
//   return (
//     <div className="bg-white rounded-lg shadow-md p-4 border border-gray-200">
//       <h3 className="text-lg font-bold text-gray-800 mb-2">📊 진행 상태</h3>
//       <p className="text-gray-600">{status}</p>

//       {progress !== null && (
//         <div className="w-full bg-gray-200 rounded-full h-4 mt-3">
//           <div
//             className="bg-blue-600 h-4 text-[12px] text-white font-bold text-center leading-4 rounded-full transition-all duration-300"
//             style={{ width: `${progress}%` }}
//           >
//             {progress}%
//           </div>
//         </div>
//       )}

//       {error && <p className="text-red-600 mt-2 font-medium">❌ 오류: {error}</p>}
//     </div>
//   );
// }

// export default StatusBar;

// components/Navbar.js
// components/StatusBar.js
// import React from 'react';

// function StatusBar({ status, progress, error }) {
//   return (
//     <div className="bg-white rounded-lg shadow-md p-4 border border-gray-200">
//       <h3 className="text-lg font-bold text-gray-800 mb-2">📊 진행 상태</h3>
//       <p className="text-gray-600">{status}</p>

//       {progress !== null && (
//         <div className="w-full bg-gray-200 rounded-full h-4 mt-3">
//           <div
//             className="bg-blue-600 h-4 text-[12px] text-white font-bold text-center leading-4 rounded-full transition-all duration-300"
//             style={{ width: `${progress}%` }}
//           >
//             {progress}%
//           </div>
//         </div>
//       )}

//       {error && <p className="text-red-600 mt-2 font-medium">❌ 오류: {error}</p>}
//     </div>
//   );
// }

// export default StatusBar;


import React from 'react';

function StatusBar({ status, progress, error, loading }) {
  return (
    <div className="bg-white rounded-lg shadow-md p-4 border border-gray-200">
      <h3 className="text-lg font-bold text-gray-800 mb-2">📊 진행 상태</h3>
      <div className="flex items-center space-x-2">
        <p className="text-gray-600">{status}</p>
        {loading && (
          <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        )}
      </div>

      {progress !== null && (
        <div className="w-full bg-gray-200 rounded-full h-4 mt-3">
          <div
            className="bg-blue-600 h-4 text-[12px] text-white font-bold text-center leading-4 rounded-full transition-all duration-300"
            style={{ width: `${progress}%` }}
          >
            {progress}%
          </div>
        </div>
      )}

      {error && <p className="text-red-600 mt-2 font-medium">❌ 오류: {error}</p>}
    </div>
  );
}

export default StatusBar;
