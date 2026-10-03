import streamlit as st

st.title("Jumbo Location Analyzer")

location = st.text_input("Enter address or shopping center")

if st.button("Analyze location"):
    st.write("Analyzing:", location)
