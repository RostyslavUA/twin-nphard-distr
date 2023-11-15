train_mwis_twin:
	echo "MWIS GDPG-Twin"
	echo "Training starts"
	python3 mwis_gcn_train_twin.py --training_set=MWISTwin --epsilon=1.0 --epsilon_min=0.002 --gamma=0.99 --feature_size=1 --diver_num=1 --datapath=./data/ER_Graph_Uniform_mixN_mixp_train0 --test_datapath=./data/ER_Graph_Uniform_GEN21_test1 --max_degree=1 --predict=mwis --learning_rate=0.0001 --learning_decay=1.0 --hidden1=32 --num_layer=3 --epochs=25 --ntrain=1

test_mwis_twin:
	echo "Testing starts"
	python3 mwis_test_complexity.py --training_set=MWISTwin --epsilon=1 --epsilon_min=0.002 --feature_size=1 --diver_num=1 --datapath=./data/ER_Graph_Uniform_GEN21_test2 --max_degree=1 --predict=mwis --learning_rate=0.00001 --hidden1=32 --num_layer=3 --opt=0

