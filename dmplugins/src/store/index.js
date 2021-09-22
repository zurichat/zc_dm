import Vue from 'vue';
import Vuex from 'vuex';
import apiServices from '../services/apiServices';

Vue.use(Vuex);
const store = {
    state: {
        pickEmoji: false,
        showReply: false,
        emojis: [],
        emojiSet: Object.create(null),
        sendMsg:'',
        recieveMsg:[],
        sender_id:'6146ce37845b436ea04d102d',
        room_id:"6146d126845b436ea04d102e",
        allSentMsg:[],
    },
    mutations: {
        setPickEmoji(state, payload) {
            state.pickEmoji = payload;
        },
        setShowReply(state, payload) {
            state.showReply = payload;
        },
        setEmojis(state, payload) {
            state.emojis = payload;
        },
        setEmojiSet(state, payload) {
            state.emojiSet = payload;
        },
        setSendMsg(state,payload){
            state.allSentMsg.push(payload)
        },
        setChat(state,newChat){
            state.sendMsg = newChat
        },
        setReceiveMsg(state,newMsg){
            state.recieveMsg = newMsg
        },

        getUserProfile(state, payload){
            // get Local time
            var options = { hour12: true };
            let today = new Date();
            state.userProfile = payload
            state.userProfile.status = true
            state.userProfile.localTime = today.toLocaleString('en-GB', options)
        }
    },
    actions: {
        setEmojis({ commit, state }, payload) {
            const emojis = [...state.emojis, payload];
            commit('setEmojis', emojis);
            const map = emojis.reduce((prev, next) => ({
                ...prev,
                [next]: (prev[next] || 0) + 1,
            }));
            commit('setEmojiSet', map);
        },
        //making API call to the backend:deveeb
        async makeRequest({commit}){
            try {
                await apiServices.getClient(this.state.room_id,this.state.sender_id,this.state.sendMsg)
                .then(result => {
                    //console.log(result.data)
                    commit('setSendMsg',result.data.data.message)
                })
            } catch (error) {
                alert(error)
            }
            this.state.sendMsg = ''    
        },
        //getting messages in room
        async getRequest({commit}){
            try {
                await apiServices.recieveClient(this.state.room_id)
                .then(result => {
                    console.log(result.data.results)
                    commit('setReceiveMsg',result.data.results)
                })
            } catch (error) {
                alert(error)
            }   
        },
        getUserProfile({commit, state}, payload){
            commit('getUserProfile',payload)
        }
    },

    getters: {
        pickEmoji(state) {
            return state.pickEmoji;
        },
        showReply(state) {
            return state.showReply;
        },
        emojis(state) {
            return state.emojis;
        },
        emojiSet(state) {
            return state.emojiSet;
        },
        getSendMsg(state){
            return state.sendMsg;
        },
        getRecieveMsg(state){
            return state.recieveMsg
        }
    },
    modules: {},
};
export default new Vuex.Store(store);
