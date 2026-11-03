import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
export default defineConfig({base:'/rich-document/dist/',plugins:[react(),tailwindcss()],build:{outDir:'.build',emptyOutDir:true,manifest:true,rollupOptions:{preserveEntrySignatures:'strict',input:{index:'index.html',reply:'src/reply-content.jsx'}}}});
